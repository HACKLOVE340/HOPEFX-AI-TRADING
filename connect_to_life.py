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
import json
import logging
import os
import pathlib
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

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
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telegram send failed: %s", exc)


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
        now = datetime.now(timezone.utc)
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


# ─────────────────────────────────────────────────────────────────────────────
# Supervisor
# ─────────────────────────────────────────────────────────────────────────────

class LifeSupervisor:
    """
    Starts HopeFXEngine and monitors it externally.

    The engine owns the full trading pipeline. This supervisor:
    - Enforces the hard daily drawdown stop (DD_HARD_STOP_PCT)
    - Sends Telegram alerts on breach and daily summary at midnight
    - Writes a checkpoint on clean shutdown
    - Handles OS signals for graceful termination
    """

    def __init__(self) -> None:
        self._tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        self._initial_bal = float(os.environ.get("INITIAL_BALANCE", "100000"))
        self._trading_mode = os.environ.get("TRADING_MODE", "paper")

        self._engine: Optional[object] = None
        self._engine_task: Optional[asyncio.Task] = None
        self._reporter = DailyReporter(self._tg_token, self._tg_chat)
        self._shutdown_event = asyncio.Event()
        self._exit_code: int = 0

    # ── public entry point ────────────────────────────────────────────────────

    async def run(self) -> int:
        """
        Start the engine and supervise it until shutdown.
        Returns exit code (0 = clean, 1 = error or DD breach).
        """
        from hopefx_engine import HopeFXEngine

        logger.info(
            "LifeSupervisor starting — mode=%s DD_limit=%.0f%%",
            self._trading_mode, DD_HARD_STOP_PCT * 100,
        )

        # Register OS signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._request_shutdown)

        # Start engine as a background task
        self._engine = HopeFXEngine()
        self._engine_task = asyncio.create_task(
            self._engine.start(), name="hopefx-engine"
        )
        self._engine_task.add_done_callback(self._on_engine_done)

        logger.info("HopeFXEngine task started — supervising")

        # Send startup Telegram notification
        await _telegram(
            self._tg_token, self._tg_chat,
            f"🟢 HOPEFX started — mode={self._trading_mode} "
            f"DD_limit={DD_HARD_STOP_PCT*100:.0f}%",
        )

        # Supervision loop
        await self._supervise()

        # Clean shutdown
        await self._stop_engine()
        await self._checkpoint()

        return self._exit_code

    # ── supervision loop ──────────────────────────────────────────────────────

    async def _supervise(self) -> None:
        """Poll engine status, enforce DD limit, send daily report."""
        heartbeat_ts = time.monotonic()

        while not self._shutdown_event.is_set():
            # If engine task died unexpectedly, stop supervising
            if self._engine_task.done():
                exc = self._engine_task.exception() if not self._engine_task.cancelled() else None
                if exc:
                    logger.critical("Engine task died with exception: %s", exc)
                    self._exit_code = 1
                break

            # Read live status from engine
            status = self._read_status()

            # ── daily drawdown hard stop ───────────────────────────────────
            dd_pct = status.get("drawdown_pct", 0.0)
            # drawdown_pct from trade_logger is already a percentage (e.g. 2.5 = 2.5%)
            dd_frac = dd_pct / 100.0
            if dd_frac >= DD_HARD_STOP_PCT:
                await self._breach_shutdown(dd_frac)
                return

            # ── daily report ───────────────────────────────────────────────
            await self._reporter.maybe_send(status)

            # ── heartbeat log ──────────────────────────────────────────────
            if time.monotonic() - heartbeat_ts >= 60:
                logger.info(
                    "HEARTBEAT  equity=%.2f balance=%.2f daily_pnl=%+.2f "
                    "dd=%.2f%% fills=%d broker=%s",
                    status.get("equity", 0),
                    status.get("balance", 0),
                    status.get("daily_pnl", 0),
                    dd_pct,
                    status.get("fill_count", 0),
                    status.get("broker", "?"),
                )
                heartbeat_ts = time.monotonic()

            await asyncio.sleep(POLL_INTERVAL)

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
        except Exception as exc:  # noqa: BLE001
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
            except Exception as exc:  # noqa: BLE001
                logger.warning("Engine stop error: %s", exc)
            finally:
                self._engine_task.cancel()
                try:
                    await self._engine_task
                except (asyncio.CancelledError, Exception):
                    pass
        logger.info("Engine stopped.")

    async def _breach_shutdown(self, dd_frac: float) -> None:
        """Hard stop triggered by daily drawdown exceeding the limit."""
        msg = (
            f"🚨 HOPEFX AUTO-STOP\n"
            f"Daily drawdown {dd_frac*100:.2f}% exceeded "
            f"{DD_HARD_STOP_PCT*100:.0f}% limit.\n"
            f"All trading halted. Manual review required."
        )
        logger.critical(
            "AUTO-STOP: daily DD %.2f%% >= %.0f%% limit",
            dd_frac * 100, DD_HARD_STOP_PCT * 100,
        )
        await _telegram(self._tg_token, self._tg_chat, msg)
        self._exit_code = 1
        self._shutdown_event.set()

    async def _checkpoint(self) -> None:
        """Persist final status to disk for post-restart recovery."""
        status = self._read_status()
        state = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trading_mode": self._trading_mode,
            "equity": status.get("equity", self._initial_bal),
            "balance": status.get("balance", self._initial_bal),
            "daily_pnl": status.get("daily_pnl", 0.0),
            "drawdown_pct": status.get("drawdown_pct", 0.0),
            "fill_count": status.get("fill_count", 0),
            "exit_code": self._exit_code,
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
    # Load .env before anything else (override=False keeps real env vars)
    load_dotenv(override=False)

    # Validate mandatory credentials
    missing = [
        k for k in ("OANDA_API_KEY", "OANDA_ACCOUNT_ID")
        if not os.environ.get(k)
    ]
    if missing:
        logger.critical("Missing required env vars: %s — aborting.", missing)
        sys.exit(1)

    # Warn if running in live mode without explicit confirmation
    if os.environ.get("TRADING_MODE", "paper").lower() == "live":
        logger.warning(
            "TRADING_MODE=live — real orders will be placed. "
            "Set TRADING_MODE=paper to use paper trading."
        )

    supervisor = LifeSupervisor()
    exit_code = await supervisor.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(_main())
