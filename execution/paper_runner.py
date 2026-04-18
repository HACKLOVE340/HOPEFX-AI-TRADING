# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
execution/paper_runner.py
=========================
Standalone paper trading runner — starts the full signal→execution loop
and produces real fills via PaperTradingBroker.

Architecture
------------
  NuclearStreamer (WebSocket tick feed)
      │  price tick
      ▼
  TickPublisher  ──► hopefx:tick (EventBus)
      │
      ▼
  SignalEngine   ──► hopefx:signal (EventBus)
      │  order_request
      ▼
  FIXRouter (PAPER_TRADING=true)
      │  routes through PaperTradingBroker
      ▼
  hopefx:order (fill_confirmation)
      │
      ▼
  FillRecorder   ──► OandaPaperClock.record_fill()
                 ──► PaperTradingGate.record_fill()

All components run as concurrent asyncio tasks. The runner handles
graceful shutdown on SIGINT/SIGTERM and logs a summary on exit.

Usage
-----
    PAPER_TRADING=true python execution/paper_runner.py

Environment variables
---------------------
    PAPER_TRADING           — must be "true" (enforced at startup)
    PAPER_SYMBOL            — instrument to trade (default: XAU/USD)
    PAPER_INITIAL_BALANCE   — starting balance in USD (default: 10000)
    PAPER_SLIPPAGE_MODEL    — gaussian | fixed | zero (default: gaussian)
    PAPER_TICK_INTERVAL_S   — seconds between REST price polls when WebSocket
                              is unavailable (default: 5)
    PAPER_SIGNAL_THRESHOLD  — minimum signal confidence to place an order
                              (default: 0.55)
    PAPER_ORDER_UNITS       — units per order (default: 1000)
    PAPER_MAX_FILLS         — stop after N fills, 0 = run forever (default: 0)
    REDIS_URL               — Redis connection string (default: redis://localhost:6379/0)
    OANDA_API_KEY           — OANDA token for live price polling fallback
    OANDA_ACCOUNT_ID        — OANDA account ID
    OANDA_PRACTICE          — "true" | "false" (default: "true")
    FIX_LATENCY_WARN_MS     — latency warning threshold in ms (default: 50)
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc

# Ensure project root is on sys.path when run directly
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("paper_runner")

# ── config ────────────────────────────────────────────────────────────────────
_SYMBOL: str = os.environ.get("PAPER_SYMBOL", "XAU/USD")
_INITIAL_BALANCE: float = float(os.environ.get("PAPER_INITIAL_BALANCE", "10000"))
_TICK_INTERVAL_S: float = float(os.environ.get("PAPER_TICK_INTERVAL_S", "5"))
_SIGNAL_THRESHOLD: float = float(os.environ.get("PAPER_SIGNAL_THRESHOLD", "0.55"))
_ORDER_UNITS: float = float(os.environ.get("PAPER_ORDER_UNITS", "1000"))
_MAX_FILLS: int = int(os.environ.get("PAPER_MAX_FILLS", "0"))


# ─────────────────────────────────────────────────────────────────────────────
# Price source — OANDA REST polling (no WebSocket dependency)
# ─────────────────────────────────────────────────────────────────────────────


class OandaPricePoll:
    """
    Polls OANDA v20 REST for the latest bid/ask on a single instrument.

    Used as the tick source when WebSocket feeds are unavailable or when
    running in a minimal environment (CI, dev machine without API keys for
    streaming providers).

    Falls back to the paper broker's internal price table when OANDA
    credentials are absent so the runner still produces fills in offline mode.
    """

    def __init__(self, symbol: str) -> None:
        self._symbol = symbol
        self._instrument = symbol.replace("/", "_")
        self._api_key = (
            os.environ.get("OANDA_API_KEY")
            or os.environ.get("BROKER_OANDA_TOKEN")
            or os.environ.get("OANDA_ACCESS_TOKEN")
            or ""
        )
        self._account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
        self._practice = os.environ.get("OANDA_PRACTICE", "true").lower() != "false"
        env_prefix = "api-fxpractice" if self._practice else "api-fxtrade"
        self._base_url = f"https://{env_prefix}.oanda.com"
        self._session: Any = None

    async def __aenter__(self) -> "OandaPricePoll":
        if self._api_key:
            try:
                import aiohttp

                self._session = aiohttp.ClientSession(
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    }
                )
            except ImportError:
                logger.warning("OandaPricePoll: aiohttp not installed — offline mode.")
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._session:
            await self._session.close()

    async def fetch(self) -> dict[str, float] | None:
        """
        Return {"bid": float, "ask": float, "mid": float} or None on failure.
        """
        if not self._session or not self._api_key:
            return None

        url = f"{self._base_url}/v3/accounts/{self._account_id}/pricing"
        params = {"instruments": self._instrument}
        try:
            async with self._session.get(
                url, params=params, timeout=__import__("aiohttp").ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    logger.warning("OandaPricePoll: HTTP %d for %s", resp.status, self._instrument)
                    return None
                data = await resp.json()
                prices = data.get("prices", [])
                if not prices:
                    return None
                p = prices[0]
                bid = float(p.get("bids", [{}])[0].get("price", 0))
                ask = float(p.get("asks", [{}])[0].get("price", 0))
                if bid <= 0 or ask <= 0:
                    return None
                mid = (bid + ask) / 2.0
                return {"bid": bid, "ask": ask, "mid": mid}
        except Exception as exc:
            logger.debug("OandaPricePoll: fetch error: %s", exc)
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Signal engine — EMA crossover on live ticks
# ─────────────────────────────────────────────────────────────────────────────


class TickSignalEngine:
    """
    Lightweight EMA crossover signal engine that runs on streaming ticks.

    Maintains two exponential moving averages (fast / slow) updated on every
    tick.  Emits a BUY signal when fast crosses above slow, SELL when it
    crosses below.  Confidence is proportional to the normalised spread
    between the two EMAs.

    This is a real implementation — no mocks, no synthetic data.  The EMAs
    are seeded from the first tick and converge within ~fast_period ticks.

    Parameters
    ----------
    fast_period : EMA half-life in ticks (default 12)
    slow_period : EMA half-life in ticks (default 26)
    threshold   : Minimum confidence to emit a signal (default 0.55)
    """

    def __init__(
        self,
        symbol: str,
        fast_period: int = 12,
        slow_period: int = 26,
        threshold: float = _SIGNAL_THRESHOLD,
    ) -> None:
        self._symbol = symbol
        self._fast_k = 2.0 / (fast_period + 1)
        self._slow_k = 2.0 / (slow_period + 1)
        self._threshold = threshold
        self._fast_ema: float | None = None
        self._slow_ema: float | None = None
        self._prev_fast: float | None = None
        self._prev_slow: float | None = None
        self._tick_count: int = 0

    def on_tick(self, mid: float) -> dict[str, Any] | None:
        """
        Update EMAs and return a signal dict if a crossover is detected.

        Returns None when no actionable signal exists (including during the
        warm-up period before both EMAs are initialised).
        """
        self._tick_count += 1

        if self._fast_ema is None:
            # Seed both EMAs with the first price
            self._fast_ema = mid
            self._slow_ema = mid
            return None

        self._prev_fast = self._fast_ema
        self._prev_slow = self._slow_ema

        self._fast_ema = mid * self._fast_k + self._fast_ema * (1 - self._fast_k)
        self._slow_ema = mid * self._slow_k + self._slow_ema * (1 - self._slow_k)

        # Detect crossover
        spread = self._fast_ema - self._slow_ema
        prev_spread = self._prev_fast - self._prev_slow

        # No crossover yet
        if (spread >= 0) == (prev_spread >= 0):
            return None

        direction = "BUY" if spread > 0 else "SELL"

        # Confidence: normalised absolute spread relative to price
        confidence = min(1.0, abs(spread) / mid * 1000)
        if confidence < self._threshold:
            return None

        return {
            "type": "signal",
            "symbol": self._symbol,
            "direction": direction,
            "confidence": round(confidence, 4),
            "fast_ema": round(self._fast_ema, 5),
            "slow_ema": round(self._slow_ema, 5),
            "mid": round(mid, 5),
            "tick_count": self._tick_count,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def status(self) -> dict[str, Any]:
        return {
            "symbol": self._symbol,
            "tick_count": self._tick_count,
            "fast_ema": self._fast_ema,
            "slow_ema": self._slow_ema,
            "threshold": self._threshold,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Fill recorder — listens on hopefx:order for fill_confirmations
# ─────────────────────────────────────────────────────────────────────────────


class FillRecorder:
    """
    Subscribes to hopefx:order and records every paper fill in:
      - OandaPaperClock (Sharpe tracker)
      - PaperTradingGate (fill counter + phase gate)
      - Local fill log (for the session summary)
    """

    def __init__(self) -> None:
        self._fills: list[dict[str, Any]] = []
        self._clock: Any = None
        self._gate: Any = None
        self._running: bool = False

    def _init_clock(self) -> None:
        try:
            from brokers.oanda_paper_clock import get_clock

            self._clock = get_clock()
        except Exception as exc:
            logger.warning("FillRecorder: OandaPaperClock unavailable: %s", exc)

    def _init_gate(self) -> None:
        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "paper_trading_gate",
                _ROOT / "research" / "pipeline" / "paper_trading_gate.py",
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self._gate = mod.PaperTradingGate()
        except Exception as exc:
            logger.warning("FillRecorder: PaperTradingGate unavailable: %s", exc)

    async def run(self, stop_event: asyncio.Event) -> None:
        """Subscribe to hopefx:order and record fills until stop_event is set."""
        from core.event_bus import CH_ORDER, bus

        self._init_clock()
        self._init_gate()
        self._running = True

        logger.info("FillRecorder: listening on hopefx:order")
        async for msg in bus.subscribe(CH_ORDER):
            if stop_event.is_set():
                break
            if msg.get("type") != "fill_confirmation":
                continue
            self._record(msg)

    def _record(self, fill: dict[str, Any]) -> None:
        """Persist fill to clock + gate and append to session log."""
        self._fills.append(fill)
        fill_n = len(self._fills)

        price = float(fill.get("price", 0))
        mid = float(fill.get("mid", price))
        direction = fill.get("direction", "BUY")

        # Fractional return: positive for profitable fills
        if mid > 0 and price > 0:
            trade_return = (price - mid) / mid * (1 if direction == "BUY" else -1)
        else:
            trade_return = 0.0

        symbol = fill.get("symbol", _SYMBOL)

        if self._clock is not None:
            try:
                self._clock.record_fill(trade_return=trade_return, symbol=symbol)
            except Exception as exc:
                logger.debug("FillRecorder: clock.record_fill error: %s", exc)

        if self._gate is not None:
            try:
                self._gate.record_fill(pnl=trade_return)
            except Exception as exc:
                logger.debug("FillRecorder: gate.record_fill error: %s", exc)

        logger.info(
            "FILL #%d  %s %s  price=%.5f  units=%.0f  source=%s",
            fill_n,
            direction,
            symbol,
            price,
            fill.get("units", 0),
            fill.get("source", "?"),
        )

    @property
    def fill_count(self) -> int:
        return len(self._fills)

    def summary(self) -> dict[str, Any]:
        return {
            "fill_count": self.fill_count,
            "fills": self._fills[-20:],  # last 20 for brevity
        }


# ─────────────────────────────────────────────────────────────────────────────
# Paper runner — orchestrates all components
# ─────────────────────────────────────────────────────────────────────────────


class PaperRunner:
    """
    Orchestrates the full paper trading loop:

      1. Ensures PAPER_TRADING=true is set in the environment.
      2. Resets the paper clock if no stamp exists.
      3. Starts FIXRouter (paper mode).
      4. Starts FillRecorder.
      5. Polls OANDA REST for ticks, runs TickSignalEngine, publishes
         order_request events to hopefx:order.
      6. Shuts down cleanly on SIGINT/SIGTERM or when _MAX_FILLS is reached.
    """

    def __init__(self) -> None:
        self._stop_event = asyncio.Event()
        self._signal_engine = TickSignalEngine(symbol=_SYMBOL)
        self._fill_recorder = FillRecorder()
        self._router: Any = None
        self._tasks: list[asyncio.Task] = []
        self._t_start: float = 0.0

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Entry point — runs until stop_event is set."""
        self._enforce_paper_mode()
        self._ensure_clock_started()

        from core.event_bus import bus

        await bus.connect()

        self._t_start = time.monotonic()
        logger.info(
            "PaperRunner starting — symbol=%s units=%.0f threshold=%.2f max_fills=%d",
            _SYMBOL,
            _ORDER_UNITS,
            _SIGNAL_THRESHOLD,
            _MAX_FILLS,
        )

        # Start FIXRouter in background
        from execution.fix_router import FIXRouter

        self._router = FIXRouter()
        router_task = asyncio.create_task(self._router.start(), name="fix_router")
        self._tasks.append(router_task)

        # Start FillRecorder in background
        recorder_task = asyncio.create_task(
            self._fill_recorder.run(self._stop_event), name="fill_recorder"
        )
        self._tasks.append(recorder_task)

        # Main tick → signal → order loop
        tick_task = asyncio.create_task(self._tick_loop(), name="tick_loop")
        self._tasks.append(tick_task)

        # Wait for stop
        await self._stop_event.wait()
        await self._shutdown()

    async def stop(self) -> None:
        """Signal the runner to stop."""
        self._stop_event.set()

    # ── tick loop ─────────────────────────────────────────────────────────────

    async def _tick_loop(self) -> None:
        """
        Poll OANDA REST for ticks, run the signal engine, publish order_requests.

        Falls back to the paper broker's internal price table when OANDA
        credentials are absent so the loop still runs in offline mode.
        """
        from core.event_bus import CH_ORDER, bus

        async with OandaPricePoll(symbol=_SYMBOL) as poller:
            while not self._stop_event.is_set():
                tick = await poller.fetch()

                if tick is None:
                    # Offline fallback: use paper broker's last known price
                    tick = self._offline_tick()

                if tick is None:
                    await asyncio.sleep(_TICK_INTERVAL_S)
                    continue

                mid = tick["mid"]

                # Publish tick to event bus so other subscribers can use it
                await bus.publish_tick(
                    {
                        "symbol": _SYMBOL,
                        "bid": tick.get("bid", mid),
                        "ask": tick.get("ask", mid),
                        "mid": mid,
                        "timestamp": time.time(),
                        "source": "oanda_rest_poll",
                    }
                )

                # Run signal engine
                signal_dict = self._signal_engine.on_tick(mid)
                if signal_dict is not None:
                    # Publish signal for observability
                    await bus.publish_signal(signal_dict)

                    # Publish order_request — FIXRouter picks this up
                    await bus.publish(
                        CH_ORDER,
                        {
                            "type": "order_request",
                            "symbol": _SYMBOL,
                            "direction": signal_dict["direction"],
                            "units": _ORDER_UNITS,
                            "mid": mid,
                            "confidence": signal_dict["confidence"],
                            "timestamp": signal_dict["timestamp"],
                        },
                    )

                    logger.info(
                        "Signal: %s %s  confidence=%.4f  mid=%.5f",
                        signal_dict["direction"],
                        _SYMBOL,
                        signal_dict["confidence"],
                        mid,
                    )

                # Check fill cap
                if _MAX_FILLS > 0 and self._fill_recorder.fill_count >= _MAX_FILLS:
                    logger.info(
                        "PaperRunner: reached MAX_FILLS=%d — stopping.", _MAX_FILLS
                    )
                    self._stop_event.set()
                    break

                await asyncio.sleep(_TICK_INTERVAL_S)

    def _offline_tick(self) -> dict[str, float] | None:
        """
        Return a tick from the paper broker's internal price table.

        Used when OANDA credentials are absent so the runner still produces
        fills in a fully offline environment.
        """
        if self._router is None or self._router._paper_broker is None:
            return None
        broker = self._router._paper_broker
        paper_symbol = _SYMBOL.replace("/", "")
        price = broker.market_prices.get(paper_symbol, 0.0)
        if price <= 0:
            return None
        return {"bid": price, "ask": price, "mid": price}

    # ── shutdown ──────────────────────────────────────────────────────────────

    async def _shutdown(self) -> None:
        """Stop all tasks and log session summary."""
        logger.info("PaperRunner: shutting down…")

        if self._router is not None:
            try:
                await self._router.stop()
            except Exception as exc:
                logger.warning("PaperRunner: router stop error: %s", exc)

        for task in self._tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        elapsed = time.monotonic() - self._t_start
        summary = self._fill_recorder.summary()
        router_metrics = self._router.metrics() if self._router else {}

        logger.info(
            "PaperRunner session complete.\n"
            "  elapsed       : %.1f s\n"
            "  fills         : %d\n"
            "  orders        : %d\n"
            "  rejects       : %d\n"
            "  signal_ticks  : %d\n"
            "  paper_mode    : %s",
            elapsed,
            summary["fill_count"],
            router_metrics.get("order_count", 0),
            router_metrics.get("reject_count", 0),
            self._signal_engine._tick_count,
            router_metrics.get("paper_mode", True),
        )

        from core.event_bus import bus

        await bus.close()

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _enforce_paper_mode() -> None:
        """Abort if PAPER_TRADING is not set — prevents accidental live execution."""
        if os.environ.get("PAPER_TRADING", "").lower() != "true":
            logger.critical(
                "PaperRunner requires PAPER_TRADING=true. "
                "Set the environment variable and retry."
            )
            sys.exit(1)

    @staticmethod
    def _ensure_clock_started() -> None:
        """
        Write a fresh paper clock stamp if none exists.

        This is the 'reset' step: if the stamp file is missing (first run or
        after reset_paper_clock.py), we stamp now so the 30-day clock begins.
        """
        try:
            from brokers.oanda_paper_clock import get_clock

            clock = get_clock()
            status = clock.status()
            if not status.get("started"):
                account_id = os.environ.get("OANDA_ACCOUNT_ID", "PENDING")
                environment = "practice" if os.environ.get("OANDA_PRACTICE", "true").lower() != "false" else "live"
                clock.maybe_start(account_id=account_id, environment=environment)
                logger.info(
                    "PaperRunner: paper clock started — account=%s env=%s",
                    account_id,
                    environment,
                )
            else:
                logger.info(
                    "PaperRunner: paper clock already running — %.1f days elapsed.",
                    status.get("elapsed_days", 0.0),
                )
        except Exception as exc:
            logger.warning("PaperRunner: clock init skipped: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


async def _async_main() -> None:
    runner = PaperRunner()

    loop = asyncio.get_running_loop()

    def _handle_signal(sig: signal.Signals) -> None:
        logger.info("PaperRunner: received %s — stopping.", sig.name)
        loop.call_soon_threadsafe(runner._stop_event.set)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal, sig)
        except (NotImplementedError, RuntimeError):
            # Windows / environments without signal support
            pass

    await runner.run()


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
