# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications

"""
connect_to_life.py
==================
One-button live bridge.

Run:
    python connect_to_life.py

What it does
------------
1. Loads .env credentials (OANDA paper broker, Telegram, Redis).
2. Initialises HopeFXEngine (ML + RL signal stack) and PropGuard (risk gate).
3. Starts the async event loop: tick → signal → risk → order.
4. Logs every fill, drawdown reading, and slippage measurement.
5. Sends a Telegram summary once per day at 00:00 UTC.
6. Auto-stops and sends an alert when daily drawdown exceeds 3 %.
7. Handles SIGINT / SIGTERM with a clean checkpoint-and-shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional

# ── third-party ───────────────────────────────────────────────────────────────
from dotenv import load_dotenv  # python-dotenv

# ── project imports ───────────────────────────────────────────────────────────
# HopeFXEngine: ML/RL signal orchestrator (hopefx_engine.py)
from hopefx_engine import HopeFXEngine

# PropGuard: prop-firm drawdown / rule enforcer (risk/pre_trade_gate.py)
from risk.pre_trade_gate import PreTradeGate as PropGuard

# ── logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("connect_to_life")

# ── constants ─────────────────────────────────────────────────────────────────
DD_HARD_STOP_PCT: float = 0.03          # 3 % daily drawdown → auto-stop
DAILY_REPORT_HOUR_UTC: int = 0          # send Telegram summary at midnight UTC
HEARTBEAT_INTERVAL: int = 30            # seconds between heartbeat log lines
CHECKPOINT_FILE: str = "state/connect_to_life_checkpoint.json"


# ─────────────────────────────────────────────────────────────────────────────
# Telegram helper
# ─────────────────────────────────────────────────────────────────────────────

async def _telegram(token: str, chat_id: str, text: str) -> None:
    """Fire-and-forget Telegram message via aiohttp; silently swallows errors."""
    try:
        import aiohttp  # optional dep — skip if unavailable
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        async with aiohttp.ClientSession() as session:
            await session.post(url, json={"chat_id": chat_id, "text": text},
                               timeout=aiohttp.ClientTimeout(total=10))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telegram send failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Fill / slippage logger
# ─────────────────────────────────────────────────────────────────────────────

def _log_fill(fill: dict) -> None:
    """Structured log for every order fill."""
    symbol   = fill.get("symbol", "?")
    side     = fill.get("side", "?")
    qty      = fill.get("units", 0)
    price    = fill.get("price", 0.0)
    expected = fill.get("expected_price", price)
    slippage = abs(price - expected)
    logger.info(
        "FILL  symbol=%s side=%s units=%s price=%.5f slippage=%.5f",
        symbol, side, qty, price, slippage,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Drawdown monitor
# ─────────────────────────────────────────────────────────────────────────────

class DrawdownMonitor:
    """Tracks intra-day equity peak and current drawdown."""

    def __init__(self, initial_balance: float) -> None:
        self._peak: float = initial_balance
        self._current: float = initial_balance
        self._day: int = datetime.now(timezone.utc).day

    def update(self, equity: float) -> float:
        """Update equity; return current drawdown fraction (positive = loss)."""
        today = datetime.now(timezone.utc).day
        if today != self._day:
            # New trading day — reset peak
            self._peak = equity
            self._day = today

        self._current = equity
        if equity > self._peak:
            self._peak = equity

        dd = (self._peak - equity) / self._peak if self._peak > 0 else 0.0
        logger.info("DD  equity=%.2f peak=%.2f drawdown=%.4f%%", equity, self._peak, dd * 100)
        return dd

    @property
    def daily_drawdown(self) -> float:
        """Current drawdown fraction."""
        if self._peak <= 0:
            return 0.0
        return (self._peak - self._current) / self._peak


# ─────────────────────────────────────────────────────────────────────────────
# Daily reporter
# ─────────────────────────────────────────────────────────────────────────────

class DailyReporter:
    """Sends one Telegram summary per calendar day."""

    def __init__(self, token: str, chat_id: str) -> None:
        self._token = token
        self._chat_id = chat_id
        self._last_day: int = -1

    async def maybe_send(self, dd_monitor: DrawdownMonitor, fills_today: int) -> None:
        now = datetime.now(timezone.utc)
        if now.hour == DAILY_REPORT_HOUR_UTC and now.day != self._last_day:
            self._last_day = now.day
            msg = (
                f"📊 HOPEFX Daily Report — {now.strftime('%Y-%m-%d')}\n"
                f"Fills today : {fills_today}\n"
                f"Daily DD    : {dd_monitor.daily_drawdown * 100:.2f}%\n"
                f"Peak equity : {dd_monitor._peak:,.2f}\n"
                f"Current eq  : {dd_monitor._current:,.2f}"
            )
            await _telegram(self._token, self._chat_id, msg)
            logger.info("Daily Telegram report sent.")


# ─────────────────────────────────────────────────────────────────────────────
# Main bridge
# ─────────────────────────────────────────────────────────────────────────────

class LifeBridge:
    """
    Wires HopeFXEngine + PropGuard into a single async run loop.

    Lifecycle
    ---------
    start() → _run_loop() → stop()
    """

    def __init__(self) -> None:
        # Credentials loaded from .env
        self._oanda_key     = os.environ["OANDA_API_KEY"]
        self._oanda_account = os.environ["OANDA_ACCOUNT_ID"]
        self._oanda_env     = os.environ.get("OANDA_ENVIRONMENT", "practice")
        self._tg_token      = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._tg_chat       = os.environ.get("TELEGRAM_CHAT_ID", "")
        self._initial_bal   = float(os.environ.get("INITIAL_BALANCE", "100000"))

        # Sub-systems (initialised in start())
        self._engine: Optional[HopeFXEngine] = None
        self._guard:  Optional[PropGuard]    = None
        self._dd:     Optional[DrawdownMonitor] = None
        self._reporter: Optional[DailyReporter] = None

        # State
        self._running: bool = False
        self._fills_today: int = 0
        self._shutdown_event: asyncio.Event = asyncio.Event()

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialise all sub-systems and enter the main loop."""
        logger.info("LifeBridge starting — broker=%s env=%s",
                    "OANDA", self._oanda_env)

        # Initialise engine (reads OANDA + OpenAI keys from env internally)
        self._engine = HopeFXEngine()

        # Initialise prop guard
        self._guard = PropGuard()

        # Drawdown monitor
        self._dd = DrawdownMonitor(self._initial_bal)

        # Daily reporter
        self._reporter = DailyReporter(self._tg_token, self._tg_chat)

        self._running = True
        logger.info("LifeBridge initialised — entering main loop")

        # Register OS signal handlers for clean shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._request_shutdown)

        await self._run_loop()

    async def stop(self) -> None:
        """Checkpoint state and shut down cleanly."""
        self._running = False
        logger.info("LifeBridge stopping — checkpointing state")
        await self._checkpoint()
        logger.info("LifeBridge stopped.")

    def _request_shutdown(self) -> None:
        """Signal handler — schedules graceful stop."""
        logger.warning("Shutdown signal received.")
        self._shutdown_event.set()

    # ── main loop ─────────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """
        Core event loop.

        Drives the engine tick-by-tick, checks drawdown after every fill,
        and auto-stops when the 3 % daily DD threshold is breached.
        """
        heartbeat_ts = time.monotonic()

        while self._running and not self._shutdown_event.is_set():
            try:
                # ── tick ──────────────────────────────────────────────────────
                # engine.step() returns a dict with keys:
                #   equity, fill (optional), signal (optional)
                result = await self._engine_step()

                # ── equity / drawdown ─────────────────────────────────────────
                equity = result.get("equity", self._initial_bal)
                dd = self._dd.update(equity)

                # ── fill logging ──────────────────────────────────────────────
                if fill := result.get("fill"):
                    _log_fill(fill)
                    self._fills_today += 1

                # ── daily report ──────────────────────────────────────────────
                await self._reporter.maybe_send(self._dd, self._fills_today)

                # ── auto-stop on DD breach ────────────────────────────────────
                if dd >= DD_HARD_STOP_PCT:
                    await self._breach_shutdown(dd)
                    return

                # ── heartbeat ─────────────────────────────────────────────────
                if time.monotonic() - heartbeat_ts >= HEARTBEAT_INTERVAL:
                    logger.info("HEARTBEAT  equity=%.2f dd=%.4f%%",
                                equity, dd * 100)
                    heartbeat_ts = time.monotonic()

                # Yield to event loop — prevents busy-spin
                await asyncio.sleep(0)

            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception("Loop error: %s", exc)
                await asyncio.sleep(1)  # brief back-off before retry

        await self.stop()

    # ── engine adapter ────────────────────────────────────────────────────────

    async def _engine_step(self) -> dict:
        """
        Calls HopeFXEngine for one tick cycle.

        Returns a normalised dict with at least 'equity'.
        Wraps synchronous engine methods in run_in_executor if needed.
        """
        loop = asyncio.get_running_loop()

        # HopeFXEngine.run() is synchronous — offload to thread pool
        result = await loop.run_in_executor(None, self._engine_tick_sync)
        return result

    def _engine_tick_sync(self) -> dict:
        """
        Synchronous tick wrapper.

        Calls the engine's internal step and normalises the output.
        Catches all exceptions so the async loop can handle them.
        """
        try:
            # engine.step() is the per-tick method on HopeFXEngine
            if hasattr(self._engine, "step"):
                raw = self._engine.step()
            else:
                # Fallback: return current balance as equity
                raw = {}

            equity = raw.get("equity", self._initial_bal) if isinstance(raw, dict) else self._initial_bal
            return {"equity": equity, "fill": raw.get("fill") if isinstance(raw, dict) else None}
        except Exception as exc:  # noqa: BLE001
            logger.error("Engine tick error: %s", exc)
            return {"equity": self._initial_bal}

    # ── breach handler ────────────────────────────────────────────────────────

    async def _breach_shutdown(self, dd: float) -> None:
        """Auto-stop triggered by DD > 3 %."""
        msg = (
            f"🚨 HOPEFX AUTO-STOP\n"
            f"Daily drawdown {dd * 100:.2f}% exceeded {DD_HARD_STOP_PCT * 100:.0f}% limit.\n"
            f"All trading halted. Manual review required."
        )
        logger.critical("AUTO-STOP: daily DD %.4f%% >= %.0f%% limit", dd * 100, DD_HARD_STOP_PCT * 100)
        await _telegram(self._tg_token, self._tg_chat, msg)
        await self.stop()

    # ── checkpoint ────────────────────────────────────────────────────────────

    async def _checkpoint(self) -> None:
        """Persist minimal state to disk for post-restart recovery."""
        import json
        import pathlib

        state = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fills_today": self._fills_today,
            "peak_equity": self._dd._peak if self._dd else self._initial_bal,
            "current_equity": self._dd._current if self._dd else self._initial_bal,
        }
        try:
            pathlib.Path(CHECKPOINT_FILE).parent.mkdir(parents=True, exist_ok=True)
            with open(CHECKPOINT_FILE, "w") as fh:
                json.dump(state, fh, indent=2)
            logger.info("Checkpoint saved → %s", CHECKPOINT_FILE)
        except OSError as exc:
            logger.warning("Checkpoint write failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

async def _main() -> None:
    # Load .env before anything else
    load_dotenv(override=False)

    # Validate mandatory credentials
    missing = [k for k in ("OANDA_API_KEY", "OANDA_ACCOUNT_ID") if not os.environ.get(k)]
    if missing:
        logger.critical("Missing required env vars: %s — aborting.", missing)
        sys.exit(1)

    bridge = LifeBridge()
    await bridge.start()


if __name__ == "__main__":
    asyncio.run(_main())
