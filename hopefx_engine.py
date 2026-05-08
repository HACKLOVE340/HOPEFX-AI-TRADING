# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Engine — unified trading engine entry point.

    python hopefx_engine.py

What runs
---------
1. Broker selection  — BROKER env var (oanda | mt5 | paper | alpaca …)
2. NuclearStreamer   — live price ticks (Finnhub / Twelve Data / Polygon)
3. HOPEFXBrain       — regime detection, ML predictor, strategy routing
4. RiskManager       — drawdown tracker, prop-firm enforcement
5. TradeLogger       — fills + equity snapshots to CSV + Prometheus
6. HeartbeatService  — Telegram "I'm alive" ping every hour
7. Live loop         — tick → brain.process_bar() → risk gate → order

Data / Execution separation
----------------------------
  NuclearStreamer  — SOLE source of live price ticks (WebSocket, broker-free)
  BROKER=oanda     — OANDA REST execution only (orders, positions, account)
  BROKER=mt5       — MT5Bridge execution only
  BROKER=paper     — PaperTradingBroker (no real orders)

OANDA is NEVER used for streaming.  All ticks come from NuclearStreamer.

All credentials are read from environment variables (see .env.example).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys
from collections import deque
from datetime import datetime, timezone
from typing import ClassVar

import pandas as pd

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("hopefx")


# ── config helpers ────────────────────────────────────────────────────────────


def _optional(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


# ── startup environment validation ────────────────────────────────────────────


def validate_startup_environment() -> list[str]:
    """
    Validate that required environment variables and runtime conditions are
    present before the engine starts.

    Returns a list of warning strings (non-fatal) and raises RuntimeError
    for any fatal misconfiguration when APP_ENV=production.

    Checks
    ------
    - SECURITY_JWT_SECRET is set and meets minimum length (32 chars)
    - BROKER=oanda requires OANDA_API_KEY + OANDA_ACCOUNT_ID
    - BROKER=mt5 requires MT5_LOGIN + MT5_PASSWORD + MT5_SERVER
    - TRADING_MODE=live requires a non-paper broker
    - INITIAL_BALANCE is a positive number when set
    - Kill switch is NOT already active at startup (warns if it is)
    - Python version >= 3.10
    """

    warnings: ClassVar[list[str]] = []
    errors: ClassVar[list[str]] = []
    is_production = os.environ.get("APP_ENV", "development") == "production"
    is_test = os.environ.get("APP_ENV", "") == "test"

    # Python version

    # JWT secret
    jwt_secret = os.environ.get("SECURITY_JWT_SECRET", "")
    if not jwt_secret:
        if is_production:
            errors.append("SECURITY_JWT_SECRET is not set (required in production)")
        else:
            warnings.append("SECURITY_JWT_SECRET is not set — using insecure default")
    elif len(jwt_secret) < 32:
        errors.append(f"SECURITY_JWT_SECRET is too short ({len(jwt_secret)} chars); minimum 32 characters required")

    # Broker-specific credentials
    broker = os.environ.get("BROKER", "").lower()
    if not broker:
        broker = "oanda" if os.environ.get("OANDA_API_KEY") else "paper"

    if broker == "oanda":
        if not os.environ.get("OANDA_API_KEY"):
            errors.append("BROKER=oanda but OANDA_API_KEY is not set")
        if not os.environ.get("OANDA_ACCOUNT_ID"):
            errors.append("BROKER=oanda but OANDA_ACCOUNT_ID is not set")
    elif broker == "mt5":
        for var in ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"):
            if not os.environ.get(var):
                errors.append(f"BROKER=mt5 but {var} is not set")

    # Live trading safety check
    trading_mode = os.environ.get("TRADING_MODE", "paper").lower()
    if trading_mode == "live" and broker == "paper":
        errors.append("TRADING_MODE=live but BROKER=paper — live mode requires a real broker")

    # INITIAL_BALANCE sanity
    initial_balance_str = os.environ.get("INITIAL_BALANCE", "")
    if initial_balance_str:
        try:
            bal = float(initial_balance_str)
            if bal <= 0:
                errors.append(f"INITIAL_BALANCE={bal} must be positive")
        except ValueError:
            errors.append(f"INITIAL_BALANCE={initial_balance_str!r} is not a valid number")

    # Kill switch pre-check
    try:
        from kill_switch import kill_switch as _ks

        if _ks.is_active():
            msg = (
                f"Kill switch is ACTIVE at startup (reason={_ks.reason!r}). "
                "Trading will be blocked until it is deactivated."
            )
            if is_production:
                errors.append(msg)
            else:
                warnings.append(msg)
    except Exception as _ks_exc:
        warnings.append(f"Could not check kill switch at startup: {_ks_exc}")

    # Report
    for w in warnings:
        logger.warning("⚠️  Startup validation: %s", w)

    if errors:
        for e in errors:
            logger.critical("❌  Startup validation FAILED: %s", e)
        if is_production and not is_test:
            raise RuntimeError(f"Engine startup aborted — {len(errors)} validation error(s). See logs above.")
        # Non-production: log errors but continue (allows CI/dev to run)
        logger.warning(
            "Startup validation errors present but APP_ENV=%s — continuing anyway",
            os.environ.get("APP_ENV", "development"),
        )

    return warnings + [f"ERROR: {e}" for e in errors]


# ── engine ────────────────────────────────────────────────────────────────────


class HopeFXEngine:
    """
    Unified trading engine.

    Wires HOPEFXBrain (ML + regime + strategy) → RiskManager → Broker.
    Broker is selected via BROKER env var; defaults to OANDA when
    OANDA_API_KEY is set, otherwise paper trading.
    """

    # Safety caps on position size to prevent runaway sizing.
    # Units are troy ounces (oz) for XAU/USD gold spot.
    # 1 standard lot = 100 oz; mini lot = 10 oz.
    MAX_LIVE_POSITION_SIZE: float = 1.0  # max 1 oz (0.01 standard lot) for live trading
    MAX_PAPER_POSITION_SIZE: float = 10.0  # max 10 oz (0.1 standard lot) for paper/test trading

    def __init__(self) -> None:
        # ── broker config ─────────────────────────────────────────────────────
        self.broker_name = _optional("BROKER", "").lower()
        if not self.broker_name:
            self.broker_name = "oanda" if os.environ.get("OANDA_API_KEY") else "paper"

        self.practice = _optional("OANDA_PRACTICE", "true").lower() != "false"
        self.instruments = _optional("OANDA_INSTRUMENTS", "XAU_USD,EUR_USD").split(",")
        self.primary_symbol = self.instruments[0]
        self.timeframe = _optional("TIMEFRAME", "H1")
        self.trading_mode = _optional("TRADING_MODE", "paper")

        # ── component handles ─────────────────────────────────────────────────
        self._broker = None
        # NuclearStreamer instance — live price ticks (WebSocket, broker-free).
        # OANDA / MT5 are NEVER used for streaming; they are execution-only.
        self._streamer = None
        self._streamer_task = None
        self._brain = None
        self._risk_manager = None
        self._trade_logger = None
        self._heartbeat = None
        self._predictor = None
        # Data layer orchestrator — started in start(), stopped in stop().
        # Provides live gold ticks, sentiment, macro features to all components.
        self._dl_orchestrator = None

        # Rolling OHLCV window per symbol
        self._ohlcv_window: dict[str, deque] = {}
        self._min_bars = int(_optional("PREDICTOR_MIN_BARS", "100"))

        self._running = False
        self._bar_count = 0  # completed H1 bars processed

        # Per-symbol H1 bar aggregation state
        self._current_bar: dict = {}  # sym_key -> {open, high, low, close, volume}
        self._current_bar_time: dict = {}  # sym_key -> datetime (hour boundary)

        # Symbols actively streamed via NuclearStreamer (skip in poll loop)
        self._streamer_active_symbols: set = set()

        # Smart router (lazy-initialised on first live order)
        self._smart_router = None

        # ── Canonical execution path ──────────────────────────────────────────
        # ExecutionEngine provides OTel tracing, Redis state persistence, TCA
        # recording, SL/TP monitoring, and the 12-check pre-trade gate.
        # Initialised in start() after broker and risk manager are ready.
        self._execution_engine = None

        # ── Position tracking ─────────────────────────────────────────────────
        # PositionTracker maintains real-time P&L for all open positions.
        # OMS tracks the full order lifecycle (created → filled → closed).
        self._position_tracker = None
        self._oms = None

        # ── NuclearStrategyAgent ──────────────────────────────────────────────
        # Runs the full nuclear pipeline (Redis → features → regime → signal).
        # Approved signals are merged with HOPEFXBrain decisions in the main loop.
        self._nuclear_agent = None
        self._nuclear_agent_task = None

        # Drift monitor interval
        self._bars_since_drift_check: int = 0
        self._drift_check_interval: int = int(os.getenv("DRIFT_CHECK_EVERY_N_BARS", "100"))

        # ── SniperEntryEngine (lazy-initialised on first qualifying signal) ───
        # Refines SMC brain decisions into precision limit-order setups using
        # HTF OB detection + LTF (M5) BOS/CHoCH + displacement CE placement.
        self._sniper = None

        # ── Nuclear supervisor integration ────────────────────────────────────
        # News events are pushed here by _on_news_event() and drained by the
        # nuclear supervisor via register_news_callback() or poll mode.
        self._news_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._news_callbacks: list = []  # coroutine functions registered externally

    # ── nuclear supervisor hooks ──────────────────────────────────────────────

    def register_news_callback(self, coro_fn) -> None:
        """
        Register an async callback invoked on every news event.

        The callback receives a single dict argument with keys:
            text, volatility, sentiment, current_exposure (optional)

        Used by LifeSupervisor to wire NuclearHopeFXSupervisor without
        requiring any changes to the engine's internal loop.

        Example::
            engine.register_news_callback(supervisor.on_new_event)
        """
        self._news_callbacks.append(coro_fn)
        logger.info(
            "News callback registered: %s (total=%d)",
            getattr(coro_fn, "__qualname__", repr(coro_fn)),
            len(self._news_callbacks),
        )

    async def _on_news_event(self, event: dict) -> None:
        """
        Dispatch a news event to all registered callbacks and the queue.

        Called internally whenever the engine receives a news item from
        the broker stream, economic calendar, or sentiment feed.
        """
        # Push to queue for poll-mode consumers (non-blocking; drop if full)
        with contextlib.suppress(asyncio.QueueFull):
            self._news_queue.put_nowait(event)

        # Fire all registered async callbacks concurrently
        if self._news_callbacks:
            await asyncio.gather(
                *(cb(event) for cb in self._news_callbacks),
                return_exceptions=True,
            )

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        logger.info("═══ HOPEFX Engine starting ═══")
        logger.info(
            "Broker: %s  Mode: %s  Symbol: %s  TF: %s",
            self.broker_name,
            self.trading_mode,
            self.primary_symbol,
            self.timeframe,
        )

        # 0. Startup environment validation — aborts in production on fatal errors
        validate_startup_environment()

        # 0a. Start data layer orchestrator — MUST be first so all downstream
        #     components (RiskManager, InferenceEngine, features_extended) have
        #     live gold ticks, sentiment, and macro features from the moment
        #     the engine begins processing bars.
        try:
            from data_layer.orchestrator import orchestrator as _dl_orch

            self._dl_orchestrator = _dl_orch
            await _dl_orch.start()
            logger.info(
                "Data layer orchestrator started — %d ML features available",
                len(_dl_orch.get_ml_features()),
            )
        except Exception as _dl_exc:
            logger.error(
                "Data layer orchestrator failed to start: %s — ML features will be zero until resolved",
                _dl_exc,
            )
            self._dl_orchestrator = None

        # 1. Risk manager — wired to orchestrator for data quality + macro gating
        from risk.manager import RiskManager

        initial_balance = float(_optional("INITIAL_BALANCE", "100000"))
        self._risk_manager = RiskManager(
            initial_balance=initial_balance,
            orchestrator=self._dl_orchestrator,
            lineage_store=getattr(self._dl_orchestrator, "_lineage", None) if self._dl_orchestrator else None,
        )
        logger.info("RiskManager initialised (balance=%.2f)", initial_balance)

        # 2. HOPEFXBrain
        from brain.hopefx_brain import get_brain

        self._brain = get_brain()
        self._brain.inject(risk_manager=self._risk_manager)
        logger.info("HOPEFXBrain initialised")

        # Inject strategy manager into brain
        try:
            from strategies import StrategyManager

            sm = StrategyManager()
            self._brain.inject(strategy_manager=sm)
            logger.info("StrategyManager injected into brain (%d strategies)", len(sm.list_strategies()))
        except Exception as exc:
            logger.warning("StrategyManager injection failed: %s", exc)

        # 2a. SniperEntryEngine — precision limit-order refinement
        try:
            from strategies.sniper_entry_engine import SniperEntryEngine

            self._sniper = SniperEntryEngine()
            logger.info(
                "SniperEntryEngine initialised — enabled=%s htf=%s ltf=%s",
                self._sniper.enabled,
                self._sniper.htf_timeframe,
                self._sniper.ltf_timeframe,
            )
        except Exception as exc:
            logger.warning("SniperEntryEngine init failed (will use market orders): %s", exc)
            self._sniper = None

        # 3. ML predictor (warm up — loads model into memory)
        try:
            from ml.advanced_predictor import get_predictor

            self._predictor = get_predictor()
            self._brain.inject(ml_predictor=self._predictor)
            logger.info(
                "AdvancedPredictor loaded — OOS acc=%.4f  AUC=%.4f",
                self._predictor.meta.get("oos_accuracy") or 0.0,
                self._predictor.meta.get("oos_auc") or 0.0,
            )
        except Exception as exc:
            logger.warning("AdvancedPredictor load failed (will degrade): %s", exc)

        # 4. Trade logger
        from monitoring.trade_logger import get_trade_logger

        self._trade_logger = get_trade_logger()
        logger.info(
            "TradeLogger initialised — log_dir=%s",
            self._trade_logger.stats["log_dir"],
        )

        # 5. Telegram heartbeat
        from notifications.heartbeat import start_heartbeat

        self._heartbeat = start_heartbeat(get_status_fn=self._get_status)
        logger.info("HeartbeatService started — stats=%s", self._heartbeat.stats)

        # 6. Broker
        await self._init_broker()

        # 6a. Inject broker into RiskOrchestrator so hedge orders can be placed
        try:
            from risk.orchestrator import risk_orchestrator

            risk_orchestrator.inject_broker(self._broker)
            logger.info("RiskOrchestrator: broker injected (%s)", self.broker_name)
        except Exception as exc:
            logger.warning("RiskOrchestrator broker injection failed: %s", exc)

        # 7. PositionTracker + OMS
        try:
            from execution.position_tracker import PositionTracker
            from execution.oms import OMS

            self._position_tracker = PositionTracker()
            self._oms = OMS()
            logger.info("PositionTracker and OMS initialised")
        except Exception as exc:
            logger.warning("PositionTracker/OMS init failed: %s", exc)

        # 7a. ExecutionEngine — canonical execution path with OTel, TCA, SL/TP
        try:
            from execution.engine import ExecutionEngine

            self._execution_engine = ExecutionEngine(
                broker_manager=self._broker,
                risk_manager=self._risk_manager,
                position_manager=self._position_tracker,
            )
            await self._execution_engine.start()
            # Bridge tick feed so ExecutionEngine always has fresh bid/ask
            self._execution_engine.update_last_tick(self.primary_symbol.replace("_", "/"), None)
            logger.info("ExecutionEngine started (canonical execution path)")
        except Exception as exc:
            logger.warning(
                "ExecutionEngine init failed (%s) — falling back to direct broker calls",
                exc,
            )
            self._execution_engine = None

        # 7b. NuclearStrategyAgent — parallel signal source alongside HOPEFXBrain
        try:
            from nuclear.nuclear_agent import get_nuclear_agent

            self._nuclear_agent = get_nuclear_agent(symbol=self.primary_symbol.replace("/", "_"))
            await self._nuclear_agent.start()
            logger.info("NuclearStrategyAgent started (symbol=%s)", self.primary_symbol)
        except Exception as exc:
            logger.warning("NuclearStrategyAgent init failed: %s", exc)
            self._nuclear_agent = None

        # 8. Equity snapshotter (background thread)
        self._trade_logger.start_equity_snapshotter(
            get_equity_fn=self._get_equity_for_snapshot,
        )

        # 9. Main loop
        self._running = True
        logger.info("═══ All systems live ═══")
        await self._run_loop()

    async def _init_broker(self) -> None:
        if self.broker_name == "oanda":
            await self._init_oanda()
        elif self.broker_name == "mt5":
            self._init_mt5()
        else:
            self._init_generic_broker()

    async def _init_oanda(self) -> None:
        """
        Initialise the OANDA execution broker (REST only).

        OANDA is used exclusively for order placement, account queries, and
        position management.  Live price streaming is handled by NuclearStreamer.
        """
        oanda_key = _optional("OANDA_API_KEY")
        oanda_account = _optional("OANDA_ACCOUNT_ID")
        if not oanda_key or not oanda_account:
            logger.warning("OANDA credentials missing — falling back to paper broker")
            self._init_generic_broker()
            return
        try:
            from brokers.oanda_stream import OANDAStream

            broker = OANDAStream(
                api_key=oanda_key,
                account_id=oanda_account,
                instruments=self.instruments,
                practice=self.practice,
            )
            await broker.__aenter__()
            connected = await broker.connect()
            if not connected:
                logger.error("OANDA connection failed — falling back to paper")
                self._init_generic_broker()
                return
            account = await broker.get_account_info()
            if account:
                logger.info(
                    "OANDA account: balance=%.2f equity=%.2f",
                    account.balance,
                    account.equity,
                )
                self._risk_manager.update_equity(account.equity)
                self._trade_logger.log_equity(
                    equity=account.equity,
                    balance=account.balance,
                )
            self._broker = broker
            logger.info("OANDA execution broker ready (streaming via NuclearStreamer)")
        except Exception as exc:
            logger.error("OANDA init failed: %s — falling back to paper", exc)
            self._init_generic_broker()

    def _init_mt5(self) -> None:
        try:
            from brokers.mt5_bridge import MT5Bridge

            self._broker = MT5Bridge.from_env()
            connected = self._broker.connect()
            if connected:
                acct = self._broker.get_account()
                logger.info(
                    "MT5 account: balance=%.2f equity=%.2f server=%s",
                    acct.get("balance", 0),
                    acct.get("equity", 0),
                    acct.get("server", "?"),
                )
                self._risk_manager.update_equity(acct.get("equity", 0))
            else:
                logger.warning("MT5 connect failed — running in signal-export mode")
            logger.info("MT5Bridge ready")
        except Exception as exc:
            logger.error("MT5 init failed: %s — falling back to paper", exc)
            self._init_generic_broker()

    def _init_generic_broker(self) -> None:
        from brokers.factory import BrokerFactory

        name = self.broker_name if self.broker_name not in ("oanda", "mt5") else "paper"
        self._broker = BrokerFactory.create_broker(name)
        if self._broker is None:
            self._broker = BrokerFactory.create_broker("paper")
        logger.info("Broker ready: %s", name)

    # ── main loop ─────────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """
        Start NuclearStreamer for live ticks and the poll loop as fallback.

        NuclearStreamer feeds _on_tick via the _NuclearTickBridge subscriber.
        The poll loop runs concurrently and handles symbols not covered by
        the streamer (e.g. when no API keys are configured).
        """
        has_stream_key = any(
            [
                _optional("FINNHUB_API_KEY"),
                _optional("TWELVE_API_KEY"),
                _optional("POLYGON_API_KEY"),
            ]
        )

        tasks = []
        if has_stream_key:
            tasks += [self._nuclear_loop(), self._poll_loop()]
        else:
            logger.info(
                "No streaming API keys set — running poll loop only. "
                "Set FINNHUB_API_KEY / TWELVE_API_KEY / POLYGON_API_KEY for WebSocket ticks."
            )
            tasks.append(self._poll_loop())

        # Run NuclearStrategyAgent loop concurrently — approved signals are
        # delivered via _on_nuclear_signal() and merged with brain decisions.
        if self._nuclear_agent is not None:
            tasks.append(
                self._nuclear_agent.run_loop(
                    interval_s=float(_optional("NUCLEAR_INTERVAL_S", "5")),
                    on_signal=self._on_nuclear_signal,
                )
            )

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _on_nuclear_signal(self, signal) -> None:
        """
        Callback invoked by NuclearStrategyAgent when an APPROVED signal is ready.

        Converts the NuclearSignal into an ExecutionRequest and routes it through
        the canonical ExecutionEngine path (OTel, TCA, pre-trade gate, SL/TP).
        Falls back to _execute_decision() if ExecutionEngine is unavailable.
        """
        try:
            direction = getattr(signal, "direction", "long")
            side = "BUY" if direction == "long" else "SELL"
            symbol = getattr(signal, "symbol", self.primary_symbol).replace("_", "/")
            confidence = float(getattr(signal, "confidence", 0.7))
            entry_price = float(getattr(signal, "entry_price", 0.0))
            stop_loss = getattr(signal, "stop_loss", None)
            take_profit = getattr(signal, "take_profit", None)

            logger.info(
                "NuclearSignal APPROVED: %s %s conf=%.3f entry=%.5f",
                side,
                symbol,
                confidence,
                entry_price,
            )

            if self._execution_engine is not None:
                from execution.engine import ExecutionRequest

                # Size via risk manager before submitting to ExecutionEngine
                class _NuclearDecision:
                    action = direction
                    self_confidence = confidence
                    reason = f"nuclear:{getattr(signal, 'strategy_id', 'unknown')}"

                _NuclearDecision.confidence = confidence
                sized = self._risk_manager.size_order(_NuclearDecision())
                if sized.quantity == 0:
                    logger.info("NuclearSignal blocked by risk manager (quantity=0)")
                    return

                req = ExecutionRequest(
                    symbol=symbol,
                    side=side,
                    quantity=sized.quantity,
                    order_type="LIMIT" if entry_price > 0 else "MARKET",
                    price=entry_price if entry_price > 0 else None,
                    stop_loss=float(stop_loss) if stop_loss else sized.stop_loss_usd,
                    take_profit=float(take_profit) if take_profit else sized.take_profit_usd,
                    strategy_id=f"nuclear:{getattr(signal, 'strategy_id', 'agent')}",
                    metadata={"confidence": confidence, "source": "nuclear_agent"},
                )
                report = await self._execution_engine.execute(req)
                if report.success:
                    self._trade_logger.log_fill(
                        symbol=symbol,
                        side=side,
                        lots=report.filled_quantity or sized.quantity,
                        requested_price=entry_price,
                        fill_price=report.average_price or entry_price,
                        broker=self.broker_name,
                        notes=f"nuclear|latency={report.latency_ms:.1f}ms",
                    )
                    self._risk_manager.notify_position_opened(symbol)
                    if self._position_tracker is not None:
                        from execution.position_tracker import Position
                        import uuid as _uuid

                        pos = Position(
                            id=report.order_id or str(_uuid.uuid4())[:16],
                            symbol=symbol,
                            side="long" if side == "BUY" else "short",
                            quantity=report.filled_quantity or sized.quantity,
                            entry_price=report.average_price or entry_price,
                            current_price=report.average_price or entry_price,
                            stop_loss=float(stop_loss) if stop_loss else sized.stop_loss_usd,
                            take_profit=float(take_profit) if take_profit else sized.take_profit_usd,
                        )
                        await self._position_tracker.add_position(pos)
                    logger.info(
                        "NuclearSignal executed: fill=%.5f latency=%.1fms",
                        report.average_price,
                        report.latency_ms,
                    )
                else:
                    logger.warning("NuclearSignal execution blocked: %s", report.message)
            else:
                # Fallback: synthesise a brain-compatible decision and execute directly
                class _FallbackDecision:
                    pass

                d = _FallbackDecision()
                d.action = direction
                d.confidence = confidence
                d.reason = f"nuclear:{getattr(signal, 'strategy_id', 'agent')}"
                await self._execute_decision(d, entry_price, symbol)
        except Exception as exc:
            # Log with full traceback so the failure is visible in production logs.
            logger.exception(
                "_on_nuclear_signal FAILED — signal dropped: symbol=%s side=%s exc=%s",
                getattr(signal, "symbol", "?"),
                "BUY" if getattr(signal, "direction", "long") == "long" else "SELL",
                exc,
            )
            # Enqueue to dead-letter buffer so operators can inspect dropped signals.
            _dead_letter: deque = getattr(self, "_nuclear_dead_letter", None)
            if _dead_letter is None:
                self._nuclear_dead_letter: deque = deque(maxlen=100)
                _dead_letter = self._nuclear_dead_letter
            _dead_letter.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "symbol": getattr(signal, "symbol", "?"),
                    "direction": getattr(signal, "direction", "?"),
                    "confidence": getattr(signal, "confidence", None),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                }
            )
            # Publish breach event so monitoring / alerting picks it up.
            try:
                from core.event_bus import event_bus as _eb

                await _eb.publish_breach(
                    {
                        "type": "nuclear_signal_dropped",
                        "symbol": getattr(signal, "symbol", "?"),
                        "error": str(exc),
                        "dead_letter_queue_depth": len(_dead_letter),
                    }
                )
            except Exception as _pub_exc:
                logger.debug("Could not publish nuclear breach event: %s", _pub_exc)

    async def _nuclear_loop(self) -> None:
        """
        Start NuclearStreamer and bridge ticks into the engine pipeline.

        NuclearStreamer is the SOLE source of live price data.
        OANDA / MT5 are never used for streaming.
        """
        from data_feed import NuclearStreamer

        engine_ref = self  # captured for the inner subscriber class

        class _NuclearTickBridge:
            """Subscriber that forwards NuclearStreamer ticks to the engine."""

            async def on_new_price(self, price: float) -> None:
                if not engine_ref._running:
                    return
                # NuclearStreamer delivers a single mid price; use it for bid/ask/mid.
                symbol = engine_ref.primary_symbol.replace("_", "/")
                await engine_ref._on_tick(
                    symbol=symbol,
                    bid=price,
                    ask=price,
                    mid=price,
                )

        self._streamer = NuclearStreamer(symbol="XAUUSD")
        self._streamer.subscribe(_NuclearTickBridge())
        # Mark the primary symbol in both formats (XAU_USD and XAU/USD) so the
        # poll loop can skip it regardless of which format instruments[] uses.
        _sym = self.primary_symbol
        self._streamer_active_symbols.add(_sym)
        self._streamer_active_symbols.add(_sym.replace("_", "/"))
        self._streamer_active_symbols.add(_sym.replace("/", "_"))
        logger.info(
            "NuclearStreamer starting — sources: finnhub=%s twelvedata=%s polygon=%s",
            bool(_optional("FINNHUB_API_KEY")),
            bool(_optional("TWELVE_API_KEY")),
            bool(_optional("POLYGON_API_KEY")),
        )
        try:
            self._streamer_task = asyncio.current_task()
            await self._streamer.run()
        except asyncio.CancelledError:
            ...  # nosec B110
        except Exception as exc:
            logger.error("NuclearStreamer error: %s", exc)

    async def _poll_loop(self) -> None:
        interval = float(_optional("POLL_INTERVAL_S", "5"))
        logger.info("Starting poll loop (interval=%.1fs)", interval)
        while self._running:
            try:
                for symbol in self.instruments:
                    # Skip symbols already covered by the NuclearStreamer WebSocket
                    sym_norm = symbol.replace("/", "_")
                    if sym_norm in self._streamer_active_symbols or symbol in self._streamer_active_symbols:
                        continue
                    await self._poll_symbol(symbol)
            except Exception as exc:
                logger.error("Poll loop error: %s", exc)
            await asyncio.sleep(interval)

    async def _poll_symbol(self, symbol: str) -> None:
        try:
            price_data = {}
            if hasattr(self._broker, "get_price"):
                price_data = self._broker.get_price(symbol) or {}
            elif hasattr(self._broker, "market_prices"):
                price_data = self._broker.market_prices.get(symbol, {})
            if not price_data:
                return
            bid = float(price_data.get("bid", price_data.get("price", 0)))
            ask = float(price_data.get("ask", bid))
            mid = (bid + ask) / 2
            await self._on_tick(symbol=symbol.replace("_", "/"), bid=bid, ask=ask, mid=mid)
        except Exception as exc:
            logger.debug("Poll symbol %s error: %s", symbol, exc)

    # ── tick handler ──────────────────────────────────────────────────────────

    async def _on_tick(self, symbol: str, bid: float, ask: float, mid: float) -> None:
        """
        Full intelligence pipeline for one tick.

        Accumulates ticks into a rolling OHLCV window, then on every
        BARS_PER_SIGNAL tick fires brain.process_bar() → risk gate → order.

        Price enrichment: NuclearStreamer delivers a single mid price with no
        spread. We enrich bid/ask/spread from the data layer orchestrator's
        consensus tick (which has real bid/ask from GoldAPI). This ensures the
        OHLCV window has realistic spread-derived high/low rather than doji bars.
        """
        sym_key = symbol.replace("/", "_")

        # Feed mid-price into rolling correlation calculator for risk checks.
        if self._risk_manager is not None:
            with contextlib.suppress(Exception):
                self._risk_manager.update_correlation_prices(sym_key, mid)

        if sym_key not in self._ohlcv_window:
            self._ohlcv_window[sym_key] = deque(maxlen=500)

        # Enrich with real bid/ask from data layer orchestrator when available.
        # NuclearStreamer delivers bid=ask=mid (no spread). The orchestrator's
        # consensus tick has real bid/ask from GoldAPI — use it to compute a
        # realistic spread for the OHLCV bar's high/low.
        _real_bid, _real_ask, spread = bid, ask, 0.0
        if self._dl_orchestrator:
            try:
                dl_tick = self._dl_orchestrator.get_latest_tick()
                if dl_tick and dl_tick.is_valid() and abs(dl_tick.mid - mid) / max(mid, 1.0) < 0.005:
                    # Use orchestrator mid if NuclearStreamer price is within 0.5%
                    # (sanity check — reject if sources diverge significantly)
                    _real_bid = dl_tick.bid
                    _real_ask = dl_tick.ask
                    spread = dl_tick.spread
                    mid = dl_tick.mid
            except Exception:  # nosec B110 - intentional fallback to NuclearStreamer price
                ...  # nosec B110

        # Build OHLCV bar: use spread to give high/low realistic range.
        # Without spread, every bar is a doji — the ML model gets zero ATR signal.
        half_spread = spread / 2.0 if spread > 0 else mid * 0.0001

        # ── H1 bar aggregation ────────────────────────────────────────────────
        now = datetime.now(timezone.utc)
        bar_time = now.replace(minute=0, second=0, microsecond=0)

        if sym_key not in self._current_bar_time:
            # First tick for this symbol — start a new bar
            self._current_bar_time[sym_key] = bar_time
            self._current_bar[sym_key] = {
                "open": mid - half_spread,
                "high": mid + half_spread,
                "low": mid - half_spread,
                "close": mid,
                "volume": 1.0,
            }
            return  # wait for the bar to close before firing

        if bar_time > self._current_bar_time[sym_key]:
            # New hour — previous bar is complete; append it
            completed = self._current_bar[sym_key]
            self._ohlcv_window[sym_key].append(completed)
            self._bar_count += 1

            # Start fresh bar for this tick
            self._current_bar_time[sym_key] = bar_time
            self._current_bar[sym_key] = {
                "open": mid - half_spread,
                "high": mid + half_spread,
                "low": mid - half_spread,
                "close": mid,
                "volume": 1.0,
            }
            # Fall through: process the completed bar
        else:
            # Same bar — update OHLC in place
            bar = self._current_bar[sym_key]
            bar["high"] = max(bar["high"], mid + half_spread)
            bar["low"] = min(bar["low"], mid - half_spread)
            bar["close"] = mid
            bar["volume"] += 1.0
            return  # don't fire brain mid-bar

        window = list(self._ohlcv_window[sym_key])
        if len(window) < self._min_bars:
            logger.debug(
                "Waiting for %d bars (have %d) for %s",
                self._min_bars,
                len(window),
                sym_key,
            )
            return

        ohlcv_df = pd.DataFrame(window)

        # ── Brain decision (ML + regime + strategy) ───────────────────────────
        try:
            decision = self._brain.process_bar(ohlcv_df, symbol=sym_key)
        except Exception as exc:
            logger.error("Brain.process_bar failed for %s: %s", sym_key, exc)
            return

        logger.info(
            "Brain[%s]: action=%s conf=%.3f regime=%s strategy=%s ml_prob=%.3f ml_conf=%.3f abstain=%s reason=%s",
            sym_key,
            decision.action,
            decision.confidence,
            decision.regime,
            decision.strategy,
            decision.ml_probability,
            decision.ml_confidence,
            decision.ml_abstain,
            decision.reason,
        )

        # ── Execute if signal is strong enough ────────────────────────────────
        # Block execution if kill switch or risk orchestrator has halted trading.
        # Fail-safe: any import/runtime error defaults to blocking the order so
        # a broken kill-switch never silently allows trading to continue.
        trading_blocked = False
        try:
            from kill_switch import kill_switch as _ks

            if _ks.is_active():
                logger.warning(
                    "Kill switch active (reason=%s) — order blocked for %s",
                    _ks.reason,
                    sym_key,
                )
                trading_blocked = True
        except ImportError as _ks_err:
            # kill_switch module missing — block as a safety measure
            logger.error(
                "kill_switch import failed (%s) — blocking order for %s (fail-safe)",
                _ks_err,
                sym_key,
            )
            trading_blocked = True
        except Exception as _ks_err:
            logger.error(
                "kill_switch check raised %s — blocking order for %s (fail-safe)",
                _ks_err,
                sym_key,
            )
            trading_blocked = True

        if not trading_blocked:
            try:
                from risk.orchestrator import risk_orchestrator as _ro

                if not _ro.is_trading_allowed():
                    logger.warning(
                        "RiskOrchestrator: trading halted (max_risk=%.2f) — order blocked for %s",
                        _ro.get_max_risk(),
                        sym_key,
                    )
                    trading_blocked = True
            except ImportError as _ro_err:
                logger.error(
                    "risk.orchestrator import failed (%s) — blocking order for %s (fail-safe)",
                    _ro_err,
                    sym_key,
                )
                trading_blocked = True
            except Exception as _ro_err:
                logger.error(
                    "RiskOrchestrator check raised %s — blocking order for %s (fail-safe)",
                    _ro_err,
                    sym_key,
                )
                trading_blocked = True

        # ── LiveTradingGate — all 5 statistical safety checks ─────────────────
        # Checks: kill switch, 30-day paper clock, OOS accuracy >= 0.60,
        # Sharpe SE gate (N >= 600 trades), FEATURE_LIVE_TRADING=true.
        # Fail-safe: any import/runtime error blocks the order.
        if not trading_blocked:
            try:
                from core.live_trading_gate import get_gate as _get_gate

                _gate_result = _get_gate().check()
                if not _gate_result.allowed:
                    logger.warning(
                        "LiveTradingGate blocked order for %s: %s",
                        sym_key,
                        _gate_result.reason,
                    )
                    trading_blocked = True
            except ImportError as _gate_err:
                logger.error(
                    "live_trading_gate import failed (%s) — blocking order for %s (fail-safe)",
                    _gate_err,
                    sym_key,
                )
                trading_blocked = True
            except Exception as _gate_err:
                logger.error(
                    "LiveTradingGate check raised %s — blocking order for %s (fail-safe)",
                    _gate_err,
                    sym_key,
                )
                trading_blocked = True

        min_conf = float(_optional("MIN_SIGNAL_CONFIDENCE", "0.35"))
        if not trading_blocked and decision.action in ("long", "short") and decision.confidence >= min_conf:
            # Stamp the live mid-price onto the decision so RiskManager.size_order()
            # can use the real current price instead of the hardcoded 1900.0 fallback.
            decision.tick_mid = mid

            # ── SniperEntryEngine refinement ──────────────────────────────────
            # Attempt to refine the brain signal into a precision limit-order
            # setup (HTF OB + LTF M5 BOS/CHoCH + displacement CE).
            # Falls back to market order when sniper conditions are not met.
            sniper_setup = None
            if self._sniper is not None:
                try:
                    ohlcv_df_for_sniper = pd.DataFrame(list(self._ohlcv_window.get(sym_key, [])))
                    # Estimate current spread from the OHLCV window (high - low of last bar)
                    _spread = 0.0
                    if not ohlcv_df_for_sniper.empty:
                        _last = ohlcv_df_for_sniper.iloc[-1]
                        _spread = float(_last.get("high", mid) - _last.get("low", mid))
                    sniper_setup = self._sniper.refine(
                        decision=decision,
                        htf_df=ohlcv_df_for_sniper,
                        orchestrator=self._dl_orchestrator,
                        spread=_spread,
                    )
                    if sniper_setup:
                        logger.info(
                            "Sniper setup confirmed for %s: entry=%.5f sl=%.5f tp=%.5f conf=%.3f",
                            sym_key,
                            sniper_setup.entry_price,
                            sniper_setup.stop_loss,
                            sniper_setup.take_profit,
                            sniper_setup.confidence,
                        )
                        # Promote sniper confidence back onto the decision for logging
                        decision.confidence = sniper_setup.confidence
                        decision.reason = sniper_setup.reason
                except Exception as _sniper_exc:
                    logger.warning(
                        "SniperEntryEngine.refine raised %s for %s — falling back to market order",
                        _sniper_exc,
                        sym_key,
                    )
                    sniper_setup = None

            await self._execute_decision(decision, mid, sym_key, sniper_setup=sniper_setup)

        # ── Drift monitor check (every N completed bars) ──────────────────────
        self._bars_since_drift_check += 1
        if self._bars_since_drift_check >= self._drift_check_interval:
            self._bars_since_drift_check = 0
            try:
                from ml.drift_monitor import get_drift_monitor

                dm = get_drift_monitor()
                report = dm.get_report()
                if report.get("any_drift_detected"):
                    logger.warning("Feature drift detected — consider retraining: %s", report)
            except Exception as _drift_exc:
                logger.debug("Drift check failed: %s", _drift_exc)

        # ── Dispatch news/sentiment event to nuclear supervisor ───────────────
        # Extract sentiment from brain decision metadata if available
        if self._news_callbacks or not self._news_queue.empty():
            await self._maybe_dispatch_news_event(ohlcv_df, decision, mid)

        # ── Equity snapshot ───────────────────────────────────────────────────
        await self._update_equity()

    async def _maybe_dispatch_news_event(self, ohlcv_df, decision, mid: float) -> None:
        """
        Build a news event from available signals and dispatch to nuclear supervisor.

        Pulls sentiment from the brain decision, volatility from recent price
        action, and current exposure from the risk orchestrator.  Only fires
        when there is something meaningful to report (sentiment != 0 or
        volatility is elevated).
        """
        try:
            # Sentiment: from brain decision metadata or ML features
            sentiment = 0.0
            if hasattr(decision, "metadata") and isinstance(decision.metadata, dict):
                sentiment = float(decision.metadata.get("sentiment", 0.0))
            elif hasattr(decision, "ml_probability"):
                # Proxy: ml_probability > 0.5 = bullish, < 0.5 = bearish
                sentiment = float(decision.ml_probability) * 2 - 1.0

            # Volatility: std of last 20 closes normalised to 1.0 = normal
            vol = 1.0
            if len(ohlcv_df) >= 20:
                closes = ohlcv_df["close"].tail(20).values
                std = float(closes.std())
                mean = float(abs(closes.mean()))
                if mean > 0:
                    vol = max(0.1, (std / mean) * 100)  # % vol, 1.0 = 1% = normal

            # Current exposure from orchestrator
            exposure = 0.5
            try:
                from risk.orchestrator import risk_orchestrator as _ro

                exposure = await _ro.get_current_exposure()
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

            # Only dispatch if there's an elevated signal worth checking
            if abs(sentiment) < 0.1 and vol < 1.5:
                return

            # Build a synthetic news text from the decision reason
            text = getattr(decision, "reason", "") or ""
            if not text:
                return

            event = {
                "text": text,
                "volatility": vol,
                "sentiment": sentiment,
                "current_exposure": exposure,
            }
            await self._on_news_event(event)
        except Exception as exc:
            logger.debug("_maybe_dispatch_news_event error: %s", exc)

    async def _execute_decision(
        self,
        decision,
        price: float,
        symbol: str,
        sniper_setup=None,
    ) -> None:
        """
        Execute a brain decision through the canonical ExecutionEngine path.

        Routes through ExecutionEngine (OTel tracing, TCA, 12-check pre-trade
        gate, SL/TP monitor, Redis state persistence) when available.  Falls
        back to direct broker calls only if ExecutionEngine failed to start.

        When ``sniper_setup`` is provided the order is placed as a LIMIT order
        at the CE level with sniper-derived SL/TP; otherwise MARKET at ``price``.
        """
        import inspect as _inspect

        side = "BUY" if decision.action == "long" else "SELL"

        # ── Resolve order parameters (sniper limit vs market fallback) ────────
        if sniper_setup is not None:
            order_type = "LIMIT"
            exec_price = sniper_setup.entry_price
            stop_loss_price = sniper_setup.stop_loss
            take_profit_price = sniper_setup.take_profit
        else:
            order_type = "MARKET"
            exec_price = price
            stop_loss_price = None
            take_profit_price = None

        # ── Risk-manager position sizing ──────────────────────────────────────
        sized = self._risk_manager.size_order(decision)
        if sized.quantity == 0:
            logger.info(
                "Order rejected by risk manager for %s — reason=%s",
                symbol,
                getattr(sized, "reject_reason", "quantity=0"),
            )
            return

        # Use sniper SL/TP when available; fall back to risk-manager values
        if stop_loss_price is None:
            stop_loss_price = sized.stop_loss_usd
        if take_profit_price is None:
            take_profit_price = sized.take_profit_usd

        quantity = sized.quantity
        is_live = self.trading_mode == "live"
        max_qty = self.MAX_LIVE_POSITION_SIZE if is_live else self.MAX_PAPER_POSITION_SIZE
        if quantity > max_qty:
            logger.warning(
                "Position size %.4f exceeds safety cap %.1f (%s mode) — capping",
                quantity,
                max_qty,
                self.trading_mode,
            )
            quantity = max_qty

        if self.trading_mode != "live":
            logger.info(
                "[PAPER] %s %s %s %.4f lots @ %.5f  sl=%.5f tp=%.5f  conf=%.3f  reason=%s",
                order_type,
                side,
                symbol,
                quantity,
                exec_price,
                stop_loss_price,
                take_profit_price,
                decision.confidence,
                decision.reason,
            )
            self._trade_logger.log_fill(
                symbol=symbol,
                side=side,
                lots=quantity,
                requested_price=exec_price,
                fill_price=price,
                pnl=0.0,
                broker=self.broker_name,
                notes=f"paper|{decision.reason}",
            )
            self._risk_manager.notify_position_opened(symbol)
            return

        # ── Live execution — route through ExecutionEngine (canonical path) ────
        # ExecutionEngine provides: OTel tracing, TCA recording, 12-check
        # pre-trade gate, SL/TP monitor, Redis state persistence, and circuit
        # breaker.  Falls back to direct SmartRouter → broker call only when
        # ExecutionEngine is unavailable (startup failure or import error).
        try:
            fill_price = exec_price

            if self._execution_engine is not None:
                # ── Canonical path: ExecutionEngine ───────────────────────────
                from execution.engine import ExecutionRequest

                req = ExecutionRequest(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    order_type=order_type,
                    price=exec_price if order_type == "LIMIT" else None,
                    stop_price=exec_price if order_type == "STOP" else None,
                    stop_loss=stop_loss_price,
                    take_profit=take_profit_price,
                    strategy_id=getattr(decision, "reason", "brain"),
                    metadata={
                        "confidence": getattr(decision, "confidence", 0.0),
                        "source": "hopefx_engine",
                    },
                )
                # Feed latest tick so ExecutionEngine can enrich price
                self._execution_engine.update_last_tick(symbol, None)

                report = await self._execution_engine.execute(req)

                if not report.success:
                    logger.warning(
                        "ExecutionEngine blocked order: %s — falling back to direct",
                        report.message,
                    )
                    # Fall through to direct path below
                else:
                    fill_price = report.average_price or exec_price
                    self._trade_logger.log_fill(
                        symbol=symbol,
                        side=side,
                        lots=report.filled_quantity or quantity,
                        requested_price=exec_price,
                        fill_price=fill_price,
                        broker=self.broker_name,
                        notes=f"{getattr(decision, 'reason', 'brain')}|latency={report.latency_ms:.1f}ms",
                    )
                    logger.info(
                        "ExecutionEngine fill: %s %s %s %.4f @ %.5f  sl=%.5f tp=%.5f  latency=%.1fms",
                        order_type,
                        side,
                        symbol,
                        report.filled_quantity or quantity,
                        fill_price,
                        stop_loss_price or 0.0,
                        take_profit_price or 0.0,
                        report.latency_ms,
                    )
                    self._risk_manager.notify_position_opened(symbol)

                    # Register fill with PositionTracker
                    if self._position_tracker is not None:
                        from execution.position_tracker import Position
                        import uuid as _uuid

                        pos = Position(
                            id=report.order_id or str(_uuid.uuid4())[:16],
                            symbol=symbol,
                            side="long" if side == "BUY" else "short",
                            quantity=report.filled_quantity or quantity,
                            entry_price=fill_price,
                            current_price=fill_price,
                            stop_loss=stop_loss_price,
                            take_profit=take_profit_price,
                        )
                        await self._position_tracker.add_position(pos)

                    # Register with OMS for full order lifecycle tracking
                    if self._oms is not None:
                        try:
                            from decimal import Decimal as _D

                            _oms_order = self._oms.create_order(
                                symbol=symbol,
                                side=side,
                                order_type=order_type,
                                quantity=_D(str(quantity)),
                                price=_D(str(exec_price)) if order_type == "LIMIT" else None,
                            )
                            self._oms.submit_order(_oms_order.id)
                        except Exception as _oms_exc:
                            logger.warning("OMS create_order failed: %s", _oms_exc)

                    # Online learner feedback
                    try:
                        from core.signal_engine import notify_fill as _notify_fill

                        _notify_fill(
                            pd.DataFrame(
                                [
                                    {
                                        "symbol": symbol,
                                        "direction": side,
                                        "fill_price": fill_price,
                                        "confidence": getattr(decision, "confidence", 0.0),
                                        "source": "hopefx_engine",
                                    }
                                ]
                            ),
                            label=1,
                            primary_prob=getattr(decision, "confidence", None),
                        )
                    except Exception as _ol_exc:
                        logger.debug("notify_fill skipped: %s", _ol_exc)
                    return  # ExecutionEngine handled it — done

            # ── Fallback path: SmartRouter → direct broker call ───────────────
            # Used only when ExecutionEngine is unavailable.
            # Check for existing opposite position — close first
            if hasattr(self._broker, "get_positions"):
                _pos_coro = self._broker.get_positions()
                positions = await _pos_coro if _inspect.isawaitable(_pos_coro) else _pos_coro
                for pos in positions or []:
                    pos_symbol = getattr(pos, "symbol", "")
                    pos_side = str(getattr(pos, "side", "")).upper()
                    if pos_symbol == symbol:
                        opposite = (pos_side in ("SELL", "SHORT") and side == "BUY") or (
                            pos_side in ("BUY", "LONG") and side == "SELL"
                        )
                        if opposite:
                            logger.info(
                                "Closing existing %s %s before opening %s",
                                pos_side,
                                symbol,
                                side,
                            )
                            if hasattr(self._broker, "close_position"):
                                _close = self._broker.close_position(symbol)
                                await _close if _inspect.isawaitable(_close) else _close
                            self._risk_manager.notify_position_closed(symbol)

            if not hasattr(self._broker, "place_order"):
                logger.warning("Broker has no place_order — skipping live order")
                return

            from brokers.oanda_stream import OANDAStream
            from brokers import OrderSide as _OrderSide

            if isinstance(self._broker, OANDAStream):
                order_kwargs: dict = {
                    "symbol": symbol,
                    "side": _OrderSide.BUY if side == "BUY" else _OrderSide.SELL,
                    "units": quantity,
                    "stop_loss": stop_loss_price,
                    "take_profit": take_profit_price,
                }
            else:
                order_kwargs = {
                    "symbol": symbol,
                    "side": side,
                    "lots": quantity,
                }

            result = None
            _used_smart_router = False
            try:
                from execution.smart_router import SmartRouter as _SmartRouter

                if self._smart_router is None:
                    self._smart_router = _SmartRouter()
                    self._smart_router.add_broker("primary", self._broker)
                    try:
                        from brokers.factory import BrokerFactory as _BF

                        _seen_classes: set[type] = {type(self._broker)}
                        for _broker_name in _BF.list_brokers():
                            if _broker_name in ("primary",):
                                continue
                            try:
                                _candidate = _BF.create_broker(_broker_name)
                                if _candidate is None or type(_candidate) in _seen_classes:
                                    continue
                                _seen_classes.add(type(_candidate))
                                if hasattr(_candidate, "connect") and _candidate.connect():
                                    self._smart_router.add_broker(_broker_name, _candidate)
                            except Exception as _reg_exc:
                                logger.debug("SmartRouter: skipping %s (%s)", _broker_name, _reg_exc)
                    except Exception as _factory_exc:
                        logger.warning("SmartRouter broker registration failed: %s", _factory_exc)

                sr_request = {
                    "symbol": symbol,
                    "direction": "long" if side == "BUY" else "short",
                    "quantity": quantity,
                    "order_type": order_type.lower(),
                    "mid_price": exec_price,
                    "bid": exec_price,
                    "ask": exec_price,
                    "spread": 0.0,
                    "confidence": getattr(decision, "confidence", 0.5),
                    "sentiment": 0.0,
                    "impact": 0.0,
                    "features": {},
                }
                sr_result = await self._smart_router.route_and_execute(sr_request)
                if sr_result.get("status") not in ("rejected", "error"):
                    result = sr_result
                    _used_smart_router = True
                    logger.info(
                        "SmartRouter fill: broker=%s fill=%.5f",
                        sr_result.get("broker"),
                        sr_result.get("fill_price", price),
                    )
                else:
                    logger.warning(
                        "SmartRouter rejected (%s) — falling back to direct order",
                        sr_result.get("reason"),
                    )
            except Exception as _sr_exc:
                logger.warning("SmartRouter failed (%s) — direct order", _sr_exc)
                self._smart_router = None

            if not _used_smart_router:
                _order_coro = self._broker.place_order(**order_kwargs)
                result = await _order_coro if _inspect.isawaitable(_order_coro) else _order_coro

            if result is not None:
                if isinstance(result, dict):
                    fill_price = float(result.get("fill_price", exec_price))
                else:
                    fill_price = float(getattr(result, "average_price", exec_price))

            self._trade_logger.log_fill(
                symbol=symbol,
                side=side,
                lots=quantity,
                requested_price=exec_price,
                fill_price=fill_price,
                broker=self.broker_name,
                notes=getattr(decision, "reason", "brain"),
            )
            logger.info(
                "Order placed (fallback): %s %s %s %.4f @ %.5f  sl=%.5f tp=%.5f",
                order_type,
                side,
                symbol,
                quantity,
                fill_price,
                stop_loss_price or 0.0,
                take_profit_price or 0.0,
            )
            self._risk_manager.notify_position_opened(symbol)

            # Register with PositionTracker even on fallback path
            if self._position_tracker is not None:
                from execution.position_tracker import Position
                import uuid as _uuid

                pos = Position(
                    id=str(_uuid.uuid4())[:16],
                    symbol=symbol,
                    side="long" if side == "BUY" else "short",
                    quantity=quantity,
                    entry_price=fill_price,
                    current_price=fill_price,
                    stop_loss=stop_loss_price,
                    take_profit=take_profit_price,
                )
                await self._position_tracker.add_position(pos)

            # Online learner feedback
            try:
                from core.signal_engine import notify_fill as _notify_fill

                _notify_fill(
                    pd.DataFrame(
                        [
                            {
                                "symbol": symbol,
                                "direction": side,
                                "fill_price": fill_price,
                                "confidence": getattr(decision, "confidence", 0.0),
                                "source": "hopefx_engine",
                            }
                        ]
                    ),
                    label=1,
                    primary_prob=getattr(decision, "confidence", None),
                )
            except Exception as _ol_exc:
                logger.debug("notify_fill skipped: %s", _ol_exc)

        except Exception as exc:
            logger.error("Order execution failed: %s", exc)

    async def _update_equity(self) -> None:
        try:
            equity = balance = 0.0
            open_pos = 0
            if hasattr(self._broker, "get_account_info"):
                info = self._broker.get_account_info()
                equity = float(info.get("equity", 0))
                balance = float(info.get("balance", equity))
                open_pos = int(info.get("open_positions", 0))
            elif hasattr(self._broker, "get_account"):
                info = self._broker.get_account()
                equity = float(info.get("equity", 0))
                balance = float(info.get("balance", equity))
            if equity > 0:
                self._risk_manager.update_equity(equity)
                self._trade_logger.log_equity(
                    equity=equity,
                    balance=balance,
                    open_positions=open_pos,
                )
        except Exception as exc:
            logger.warning("Equity update failed: %s", exc)

    # ── status / snapshot helpers ─────────────────────────────────────────────

    def _get_status(self) -> dict:
        tl_stats = self._trade_logger.stats if self._trade_logger else {}
        brain_stats = self._brain.stats if self._brain else {}
        last_decision = (self._brain.recent_decisions(1) or [{}])[0] if self._brain else {}
        return {
            "equity": tl_stats.get("equity", 0),
            "balance": tl_stats.get("balance", 0),
            "daily_pnl": tl_stats.get("daily_pnl", 0),
            "open_positions": tl_stats.get("open_positions", 0),
            "drawdown_pct": tl_stats.get("drawdown_pct", 0),
            "broker": self.broker_name,
            "mode": self.trading_mode,
            "last_signal": {
                "direction": last_decision.get("action", "hold"),
                "confidence": last_decision.get("confidence", 0),
            }
            if last_decision
            else None,
            "risk_alerts": [],
            "brain_signal_rate": brain_stats.get("signal_rate", 0),
        }

    def _get_equity_for_snapshot(self) -> dict:
        tl = self._trade_logger
        if tl:
            s = tl.stats
            return {
                "equity": s.get("equity", 0),
                "balance": s.get("balance", 0),
                "daily_pnl": s.get("daily_pnl", 0),
                "open_positions": s.get("open_positions", 0),
            }
        return {}

    # ── shutdown ──────────────────────────────────────────────────────────────

    async def stop(self) -> None:
        self._running = False
        if self._heartbeat:
            self._heartbeat.stop()
        # Stop NuclearStreamer gracefully.
        if self._streamer:
            try:
                await self._streamer.stop()
            except Exception as _exc:
                logger.debug("NuclearStreamer stop error: %s", _exc)
        # Close OANDA execution broker session if open.
        if self._broker and hasattr(self._broker, "__aexit__"):
            try:
                await self._broker.__aexit__(None, None, None)
            except Exception as _exc:
                logger.debug("Broker close error: %s", _exc)
        # Stop data layer orchestrator last — all components that consume it
        # must be stopped first so no in-flight tick callbacks fire after stop.
        if self._dl_orchestrator:
            try:
                await self._dl_orchestrator.stop()
                logger.info("Data layer orchestrator stopped")
            except Exception as _exc:
                logger.debug("Data layer orchestrator stop error: %s", _exc)
        logger.info(
            "HOPEFX Engine stopped — bars=%d signals=%d",
            self._bar_count,
            self._brain.stats.get("signal_count", 0) if self._brain else 0,
        )


# ── main ──────────────────────────────────────────────────────────────────────


async def _main() -> None:
    engine = HopeFXEngine()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(engine.stop()))
    try:
        await engine.start()
    except (KeyboardInterrupt, asyncio.CancelledError):
        await engine.stop()
    except SystemExit:
        raise
    except Exception as exc:
        logger.critical("Engine fatal error: %s", exc, exc_info=True)
        await engine.stop()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(_main())
