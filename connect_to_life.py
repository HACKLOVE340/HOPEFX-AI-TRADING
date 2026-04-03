# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
connect_to_life.py
==================
Supervisor that starts HopeFXEngine and enforces hard safety limits.

Run:
    python connect_to_life.py                  # paper mode (default)
    TRADING_MODE=live python connect_to_life.py  # live mode

What it does
------------
1. Loads .env credentials (OANDA, Telegram, Redis).
2. Validates all required environment variables before starting.
3. Starts HopeFXEngine as an asyncio task — the engine owns the full
   tick → brain → risk → order pipeline internally.
4. Polls engine status every POLL_INTERVAL seconds and logs a heartbeat.
5. Enforces a hard daily drawdown stop (DD_HARD_STOP_PCT, default 3 %).
   When breached: stops the engine, sends a Telegram alert, exits 1.
6. Sends a Telegram daily summary at midnight UTC.
7. Handles SIGINT / SIGTERM with a clean checkpoint-and-shutdown.
8. Writes a JSON checkpoint on every clean stop for post-restart recovery.
9. Starts HOPEFXBrain (security/global_fortress.py) as a 24/7 background
   task — scans routes, traces attacks, auto-heals code, triggers lockdown.

Architecture
------------
HopeFXEngine.start() runs its own complete async event loop:
  OANDA stream → _on_tick() → HOPEFXBrain → PreTradeGate → broker.place_order()

This supervisor does NOT drive the engine tick-by-tick. It monitors the
engine's published status (via engine._get_status()) and enforces limits
that are outside the engine's own scope (hard DD stop, daily report).

The PreTradeGate (PropGuard) is already wired inside HopeFXEngine.start().
Instantiating it separately here would duplicate risk checks — do not do that.

Environment variables
---------------------
Required:
  OANDA_API_KEY          OANDA v20 API key
  OANDA_ACCOUNT_ID       OANDA account ID

Optional:
  TRADING_MODE           paper (default) | live
  INITIAL_BALANCE        starting equity for DD calculation (default 100000)
  DD_HARD_STOP_PCT       daily drawdown fraction to trigger auto-stop (default 0.03)
  POLL_INTERVAL          status poll interval in seconds (default 5)
  TELEGRAM_BOT_TOKEN     Telegram bot token for alerts
  TELEGRAM_CHAT_ID       Telegram chat ID for alerts
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import pathlib
import signal
import sys
import time
from datetime import UTC, datetime
from typing import Any, ClassVar

from dotenv import load_dotenv

# ── Nuclear chart engine (optional — graceful degradation if unavailable) ─────
_chart_engine = None


def _get_chart_engine():
    """Lazy-load the NuclearAIChartEngine singleton."""
    global _chart_engine
    if _chart_engine is None:
        try:
            from charting.nuclear_ai_chart_engine import get_chart_engine

            _chart_engine = get_chart_engine()
        except Exception as _exc:
            logger.debug("Chart engine unavailable (optional): %s", _exc)
    return _chart_engine


# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("connect_to_life")

# ── constants (overridable via env) ───────────────────────────────────────────
DD_HARD_STOP_PCT: float = float(os.environ.get("DD_HARD_STOP_PCT", "0.03"))
POLL_INTERVAL: int = int(os.environ.get("POLL_INTERVAL", "5"))
DAILY_REPORT_HOUR_UTC: int = 0
CHECKPOINT_FILE: str = "state/connect_to_life_checkpoint.json"

# Log message constant — used in multiple except blocks throughout this module
_SUPPRESSED_EXC_MSG = "Suppressed exception: %s"

# Nuclear supervisor — controls whether it is active
NUCLEAR_SUPERVISOR_ENABLED: bool = os.environ.get("NUCLEAR_SUPERVISOR_ENABLED", "1") != "0"


# ─────────────────────────────────────────────────────────────────────────────
# Telegram helper
# ─────────────────────────────────────────────────────────────────────────────


async def _telegram(token: str, chat_id: str, text: str) -> None:
    """Fire-and-forget Telegram message. Silently swallows errors."""
    if not token or not chat_id:
        return
    try:
        import aiohttp

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        async with aiohttp.ClientSession() as session:
            await session.post(
                url,
                json={"chat_id": chat_id, "text": text},
                timeout=aiohttp.ClientTimeout(total=10),
            )
    except Exception as exc:
        logger.warning("Telegram send failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Drawdown monitor
# ─────────────────────────────────────────────────────────────────────────────


class DrawdownMonitor:
    """Track peak-to-trough drawdown for a running equity series.

    Usage::

        dm = DrawdownMonitor(initial_balance=100_000)
        dd_frac = dm.update(current_equity)   # returns drawdown fraction 0..1

    Attributes
    ----------
    daily_drawdown : float
        Drawdown fraction relative to the *initial* balance supplied at
        construction (proxy for daily drawdown when reset each session).
    """

    def __init__(self, initial_balance: float) -> None:
        self._peak: float = initial_balance
        self._initial: float = initial_balance

    def update(self, equity: float) -> float:
        """Update peak and return current drawdown fraction (0.0 = no drawdown)."""
        self._last_equity = equity
        self._peak = max(self._peak, equity)
        if self._peak <= 0:
            return 0.0
        return max(0.0, (self._peak - equity) / self._peak)

    @property
    def daily_drawdown(self) -> float:
        """Drawdown fraction relative to the initial balance.

        Tracks how far the *current* equity has fallen from the initial
        balance, regardless of any intra-session peaks above that baseline.
        """
        # _last_equity is updated by update(); fall back to _peak when not set.
        current = getattr(self, "_last_equity", self._peak)
        if self._initial <= 0:
            return 0.0
        return max(0.0, (self._initial - current) / self._initial)

    # Allow external code to reset the daily baseline
    def reset_daily(self, balance: float) -> None:
        """Reset the daily baseline to *balance* (call at session start)."""
        self._initial = balance
        self._peak = max(self._peak, balance)


# ─────────────────────────────────────────────────────────────────────────────
# Daily reporter
# ─────────────────────────────────────────────────────────────────────────────


class DailyReporter:
    """Sends one Telegram summary per calendar day at midnight UTC."""

    def __init__(self, token: str, chat_id: str) -> None:
        self._token = token
        self._chat_id = chat_id
        self._last_day: int = -1

    async def maybe_send(self, status: dict) -> None:
        now = datetime.now(UTC)
        if now.hour != DAILY_REPORT_HOUR_UTC or now.day == self._last_day:
            return
        self._last_day = now.day
        equity = status.get("equity", 0)
        balance = status.get("balance", 0)
        daily_pnl = status.get("daily_pnl", 0)
        dd_pct = status.get("drawdown_pct", 0)
        fills = status.get("fill_count", 0)
        msg = (
            f"📊 HOPEFX Daily Report — {now.strftime('%Y-%m-%d')}\n"
            f"Equity      : {equity:,.2f}\n"
            f"Balance     : {balance:,.2f}\n"
            f"Daily P&L   : {daily_pnl:+,.2f}\n"
            f"Drawdown    : {dd_pct:.2f}%\n"
            f"Fills today : {fills}\n"
            f"Broker      : {status.get('broker', '?')}"
        )
        await _telegram(self._token, self._chat_id, msg)
        logger.info("Daily Telegram report sent.")


# ===========================================================================
# Supervisor
# ===========================================================================


class LifeSupervisor:
    """
    Starts HopeFXEngine and monitors it externally.

    The engine owns the full trading pipeline. This supervisor:
    - Enforces the hard daily drawdown stop (DD_HARD_STOP_PCT)
    - Sends Telegram alerts on breach and daily summary at midnight
    - Writes a checkpoint on clean shutdown
    - Handles OS signals for graceful termination
    - Runs NuclearHopeFXSupervisor for RL-powered event response
    """

    def __init__(self) -> None:
        self._tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        self._initial_bal = float(os.environ.get("INITIAL_BALANCE", "100000"))
        self._trading_mode = os.environ.get("TRADING_MODE", "paper")

        self._engine: object | None = None
        self._engine_task: asyncio.Task | None = None
        self._reporter = DailyReporter(self._tg_token, self._tg_chat)
        self._shutdown_event = asyncio.Event()
        self._exit_code: int = 0

        # Nuclear supervisor (RL-powered event response)
        self._nuclear_supervisor = None
        if NUCLEAR_SUPERVISOR_ENABLED:
            try:
                from brain.nuclear_supervisor import get_nuclear_supervisor

                self._nuclear_supervisor = get_nuclear_supervisor()
                logger.info("NuclearHopeFXSupervisor loaded and ready")
            except Exception as exc:
                logger.warning("NuclearHopeFXSupervisor unavailable: %s", exc)

        # Nuclear chart engine (real-time dashboard data)
        self._chart_engine = _get_chart_engine()
        if self._chart_engine is not None:
            logger.info("NuclearAIChartEngine attached to LifeSupervisor")

    # ── public entry point ────────────────────────────────────────────────────

    async def run(self) -> int:
        """
        Start the engine and supervise it until shutdown.
        Returns exit code (0 = clean, 1 = error or DD breach).
        """
        from hopefx_engine import HopeFXEngine

        logger.info(
            "LifeSupervisor starting — mode=%s DD_limit=%.0f%%",
            self._trading_mode,
            DD_HARD_STOP_PCT * 100,
        )

        # Register OS signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._request_shutdown)

        # Start engine as a background task
        self._engine = HopeFXEngine()
        self._engine_task = asyncio.create_task(self._engine.start(), name="hopefx-engine")
        self._engine_task.add_done_callback(self._on_engine_done)

        logger.info("HopeFXEngine task started — supervising")

        # Wire nuclear supervisor event callback into the engine if supported
        if self._nuclear_supervisor is not None:
            self._wire_nuclear_supervisor()

        # Start nuclear chart engine tick loop as a background task
        if self._chart_engine is not None:
            _t = asyncio.create_task(self._chart_engine.start(), name="nuclear-chart-engine")
            _t.add_done_callback(lambda _: None)
            logger.info("NuclearAIChartEngine tick loop started")

        # Start HOPEFXBrain — 24/7 security engine (global_fortress)
        try:
            from security.global_fortress import start_brain as _start_brain

            # app reference: import the FastAPI app so the brain can mount its router
            try:
                from app import app as _fastapi_app

                await _start_brain(_fastapi_app)
                logger.info("HOPEFXBrain 24/7 security engine started")
            except ImportError:
                # connect_to_life may run without the full FastAPI app (CLI mode).
                # Create a minimal FastAPI instance so the brain can mount its router
                # and run its 24/7 monitor loop without the full HTTP server.
                from fastapi import FastAPI as _FastAPI

                _minimal_app = _FastAPI(title="HOPEFXBrain-CLI")
                await _start_brain(_minimal_app)
                logger.info("HOPEFXBrain started in CLI mode (minimal FastAPI instance)")
        except Exception as _brain_exc:
            logger.warning("HOPEFXBrain failed to start (non-fatal): %s", _brain_exc)

        # Start AntivirusScanner — multi-layer malware detection
        try:
            from security.antivirus import start_av_scanner as _start_av

            try:
                from app import app as _fastapi_app_av
                await _start_av(_fastapi_app_av)
            except ImportError:
                from fastapi import FastAPI as _FastAPI
                _minimal_av_app = _FastAPI(title="AV-CLI")
                await _start_av(_minimal_av_app)
            logger.info("AntivirusScanner started")
        except Exception as _av_exc:
            logger.warning("AntivirusScanner failed to start (non-fatal): %s", _av_exc)

        # Start SelfHealer — code integrity monitor + auto-patch applier
        try:
            from security.self_healer import start_healer as _start_healer

            try:
                from app import app as _fastapi_app_heal
                await _start_healer(_fastapi_app_heal)
            except ImportError:
                from fastapi import FastAPI as _FastAPI
                _minimal_heal_app = _FastAPI(title="SelfHealer-CLI")
                await _start_healer(_minimal_heal_app)
            logger.info("SelfHealer code integrity monitor started")
        except Exception as _heal_exc:
            logger.warning("SelfHealer failed to start (non-fatal): %s", _heal_exc)

        # Send startup Telegram notification
        nuclear_status = "RL-supervisor=ON" if self._nuclear_supervisor is not None else "RL-supervisor=OFF"
        await _telegram(
            self._tg_token,
            self._tg_chat,
            f"🟢 HOPEFX started — mode={self._trading_mode} DD_limit={DD_HARD_STOP_PCT * 100:.0f}% {nuclear_status}",
        )

        # Supervision loop
        await self._supervise()

        # Clean shutdown
        await self._stop_engine()
        await self._checkpoint()

        return self._exit_code

    # ── nuclear supervisor wiring ─────────────────────────────────────────────

    def _wire_nuclear_supervisor(self) -> None:
        """
        Register the nuclear event callback with the engine's news feed.

        The engine exposes an optional ``register_news_callback(coro)`` hook.
        If that hook is absent we fall back to a polling approach that reads
        news events from the engine's internal queue each supervision cycle.
        """
        if self._engine is None or self._nuclear_supervisor is None:
            return

        if hasattr(self._engine, "register_news_callback"):
            try:
                self._engine.register_news_callback(self.on_news_event)
                logger.info("Nuclear supervisor wired via register_news_callback")
                return
            except Exception as exc:
                logger.warning("register_news_callback failed: %s — using poll mode", exc)

        # Fallback: polling mode — _supervise will call _poll_news_events()
        logger.info("Nuclear supervisor in poll mode (no register_news_callback on engine)")

    async def on_news_event(self, event: dict[str, Any]) -> None:
        """
        Callback invoked by the engine (or news feed) on each new event.

        The event dict must contain at minimum ``text``.  Optional keys:
        ``volatility``, ``sentiment``, ``current_exposure``.

        If current_exposure is not provided we read it from the risk
        orchestrator so the RL agent always has an accurate portfolio view.
        """
        if self._nuclear_supervisor is None:
            return

        # Enrich with live exposure if not already present
        if "current_exposure" not in event:
            try:
                from risk.orchestrator import risk_orchestrator

                event["current_exposure"] = await risk_orchestrator.get_current_exposure()
            except Exception:
                event["current_exposure"] = 0.5

        try:
            result = await self._nuclear_supervisor.on_new_event(event)
            action = result.get("action_taken", "unknown")

            # Forward scored event to chart engine for real-time dashboard update
            if self._chart_engine is not None:
                try:
                    self._chart_engine.inject_news_event(
                        text=event.get("text", ""),
                        volatility=event.get("volatility", 1.0),
                        sentiment=event.get("sentiment", 0.0),
                    )
                except Exception as _exc:
                    logger.debug(_SUPPRESSED_EXC_MSG, _exc)  # chart engine errors must never crash the supervisor

            # If nuclear mode was triggered, enforce DD stop immediately
            if action == "nuclear":
                logger.critical("Nuclear mode triggered by event — initiating emergency shutdown")
                self._exit_code = 1
                self._shutdown_event.set()
        except Exception as exc:
            logger.error("Nuclear supervisor event processing error: %s", exc)

    async def _poll_news_events(self) -> None:
        """
        Poll-mode fallback: drain any pending news events from the engine's
        internal queue and forward them to the nuclear supervisor.
        """
        if self._engine is None or self._nuclear_supervisor is None:
            return

        queue = getattr(self._engine, "_news_queue", None)
        if queue is None:
            return

        while not queue.empty():
            try:
                event = queue.get_nowait()
                await self.on_news_event(event)
            except Exception:
                break

    # ── supervision loop ──────────────────────────────────────────────────────

    async def _supervise(self) -> None:
        """Poll engine status, enforce DD limit, send daily report."""
        heartbeat_ts = time.monotonic()

        while not self._shutdown_event.is_set():
            if self._engine_task.done():
                self._handle_engine_done()
                break

            status = self._read_status()
            dd_pct = status.get("drawdown_pct", 0.0)
            dd_frac = dd_pct / 100.0

            if dd_frac >= DD_HARD_STOP_PCT:
                await self._breach_shutdown(dd_frac)
                return

            await self._reporter.maybe_send(status)
            await self._poll_news_events()
            self._record_chart_equity(status)

            heartbeat_ts = self._maybe_log_heartbeat(status, dd_pct, heartbeat_ts)

            await asyncio.sleep(POLL_INTERVAL)

    def _handle_engine_done(self) -> None:
        """Handle an unexpectedly finished engine task."""
        exc = self._engine_task.exception() if not self._engine_task.cancelled() else None
        if exc:
            logger.critical("Engine task died with exception: %s", exc)
            self._exit_code = 1

    def _nuclear_annotation(self) -> str | None:
        """Return a chart annotation string based on current nuclear supervisor state."""
        if self._nuclear_supervisor is None:
            return None
        ns = self._nuclear_supervisor.get_status()
        if ns.get("nuclear_level", 0) >= 2:
            return f"NUC-L{ns['nuclear_level']}"
        if ns.get("trading_paused"):
            return "PAUSED"
        return None

    def _record_chart_equity(self, status: dict) -> None:
        """Record an equity point on the nuclear chart engine (non-fatal)."""
        if self._chart_engine is None:
            return
        try:
            equity = status.get("equity", self._initial_bal)
            balance = status.get("balance", self._initial_bal)
            self._chart_engine.record_equity_point(equity, balance, self._nuclear_annotation())
        except Exception as _exc:
            logger.debug(_SUPPRESSED_EXC_MSG, _exc)  # chart engine errors must never crash the supervisor

    def _nuclear_info_str(self) -> str:
        """Return a formatted nuclear supervisor status string for heartbeat logs."""
        if self._nuclear_supervisor is None:
            return ""
        ns = self._nuclear_supervisor.get_status()
        return (
            f" nuclear_level={ns['nuclear_level']}"
            f" paused={ns['trading_paused']}"
            f" rl={'on' if ns['rl_agent_loaded'] else 'off'}"
        )

    def _maybe_log_heartbeat(self, status: dict, dd_pct: float, heartbeat_ts: float) -> float:
        """Log a heartbeat if 60 s have elapsed; return updated timestamp."""
        if time.monotonic() - heartbeat_ts < 60:
            return heartbeat_ts
        logger.info(
            "HEARTBEAT  equity=%.2f balance=%.2f daily_pnl=%+.2f dd=%.2f%% fills=%d broker=%s%s",
            status.get("equity", 0),
            status.get("balance", 0),
            status.get("daily_pnl", 0),
            dd_pct,
            status.get("fill_count", 0),
            status.get("broker", "?"),
            self._nuclear_info_str(),
        )
        return time.monotonic()

    def _read_status(self) -> dict:
        """
        Read current engine status safely.

        Returns a dict with keys: equity, balance, daily_pnl, drawdown_pct,
        open_positions, fill_count, broker. Falls back to zeros on any error.
        """
        try:
            if self._engine and hasattr(self._engine, "_get_status"):
                status = self._engine._get_status()
                # Merge fill_count from trade_logger.stats if available
                tl = getattr(self._engine, "_trade_logger", None)
                if tl:
                    status["fill_count"] = tl.stats.get("fill_count", 0)
                return status
        except Exception as exc:
            logger.warning("Status read error: %s", exc)
        return {
            "equity": self._initial_bal,
            "balance": self._initial_bal,
            "daily_pnl": 0.0,
            "drawdown_pct": 0.0,
            "open_positions": 0,
            "fill_count": 0,
            "broker": "?",
        }

    # ── shutdown helpers ──────────────────────────────────────────────────────

    def _request_shutdown(self) -> None:
        """OS signal handler — schedules graceful stop."""
        logger.warning("Shutdown signal received — stopping cleanly.")
        self._shutdown_event.set()

    def _on_engine_done(self, task: asyncio.Task) -> None:
        """Callback when engine task finishes (normally or with error)."""
        if task.cancelled():
            logger.info("Engine task cancelled.")
        elif task.exception():
            logger.error("Engine task raised: %s", task.exception())
            self._exit_code = 1
            self._shutdown_event.set()
        else:
            logger.info("Engine task completed normally.")
            self._shutdown_event.set()

    async def _stop_engine(self) -> None:
        """Stop the engine task gracefully."""
        if self._engine_task and not self._engine_task.done():
            try:
                if self._engine and hasattr(self._engine, "stop"):
                    await self._engine.stop()
            except Exception as exc:
                logger.warning("Engine stop error: %s", exc)
            finally:
                self._engine_task.cancel()
                with contextlib.suppress((asyncio.CancelledError, Exception)):
                    await self._engine_task
        logger.info("Engine stopped.")

        # Stop nuclear chart engine cleanly
        if self._chart_engine is not None:
            try:
                await self._chart_engine.stop()
            except Exception as _exc:
                logger.debug(_SUPPRESSED_EXC_MSG, _exc)

        # Stop notifications manager cleanly
        try:
            from notifications import notifications

            await notifications.stop()
        except Exception as _exc:
            logger.debug(_SUPPRESSED_EXC_MSG, _exc)

    async def _breach_shutdown(self, dd_frac: float) -> None:
        """Hard stop triggered by daily drawdown exceeding the limit."""
        msg = (
            f"🚨 HOPEFX AUTO-STOP\n"
            f"Daily drawdown {dd_frac * 100:.2f}% exceeded "
            f"{DD_HARD_STOP_PCT * 100:.0f}% limit.\n"
            f"All trading halted. Manual review required."
        )
        logger.critical(
            "AUTO-STOP: daily DD %.2f%% >= %.0f%% limit",
            dd_frac * 100,
            DD_HARD_STOP_PCT * 100,
        )
        await _telegram(self._tg_token, self._tg_chat, msg)
        self._exit_code = 1
        self._shutdown_event.set()

    async def _checkpoint(self) -> None:
        """Persist final status to disk for post-restart recovery."""
        status = self._read_status()
        nuclear_state: ClassVar[dict] = {}
        if self._nuclear_supervisor is not None:
            try:
                nuclear_state = self._nuclear_supervisor.get_status()
                # Remove non-serialisable last_event nested dict for simplicity
                nuclear_state.pop("last_event", None)
            except Exception as _exc:
                logger.debug(_SUPPRESSED_EXC_MSG, _exc)
        state = {
            "timestamp": datetime.now(UTC).isoformat(),
            "trading_mode": self._trading_mode,
            "equity": status.get("equity", self._initial_bal),
            "balance": status.get("balance", self._initial_bal),
            "daily_pnl": status.get("daily_pnl", 0.0),
            "drawdown_pct": status.get("drawdown_pct", 0.0),
            "fill_count": status.get("fill_count", 0),
            "exit_code": self._exit_code,
            "nuclear": nuclear_state,
        }
        try:
            pathlib.Path(CHECKPOINT_FILE).parent.mkdir(parents=True, exist_ok=True)
            with open(CHECKPOINT_FILE, "w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=2)
            logger.info("Checkpoint saved → %s", CHECKPOINT_FILE)
        except OSError as exc:
            logger.warning("Checkpoint write failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


async def _main() -> None:
    # Load .env before anything else (override=False keeps real env vars)
    load_dotenv(override=False)

    # Validate mandatory credentials
    missing = [k for k in ("OANDA_API_KEY", "OANDA_ACCOUNT_ID") if not os.environ.get(k)]
    if missing:
        logger.critical("Missing required env vars: %s — aborting.", missing)
        sys.exit(1)

    # Warn if running in live mode without explicit confirmation
    if os.environ.get("TRADING_MODE", "paper").lower() == "live":
        logger.warning("TRADING_MODE=live — real orders will be placed. Set TRADING_MODE=paper to use paper trading.")

    supervisor = LifeSupervisor()
    exit_code = await supervisor.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(_main())
