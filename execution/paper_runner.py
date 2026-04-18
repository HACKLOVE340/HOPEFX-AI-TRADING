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
import contextlib

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

    async def __aenter__(self) -> OandaPricePoll:
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
# OHLCV buffer — accumulates ticks into 1-minute bars for InferenceEngine
# ─────────────────────────────────────────────────────────────────────────────

# Minimum bars required before InferenceEngine will produce a non-neutral signal
_OHLCV_MIN_BARS: int = int(os.environ.get("PAPER_OHLCV_MIN_BARS", "100"))
# Bar period in seconds (default 60 s = 1-minute bars)
_BAR_PERIOD_S: float = float(os.environ.get("PAPER_BAR_PERIOD_S", "60"))
# Maximum bars to keep in the rolling window (memory cap)
_OHLCV_MAX_BARS: int = int(os.environ.get("PAPER_OHLCV_MAX_BARS", "500"))


class OHLCVBuffer:
    """
    Accumulates streaming mid-price ticks into fixed-period OHLCV bars.

    Each bar covers ``_BAR_PERIOD_S`` seconds.  Volume is approximated as
    the tick count within the bar (no real volume data from REST polling).
    The buffer is capped at ``_OHLCV_MAX_BARS`` bars to bound memory.

    Call ``on_tick(mid, ts)`` for every price update.
    Call ``dataframe()`` to get the current OHLCV DataFrame for inference.
    Call ``bar_count`` to check whether the warm-up period is complete.
    """

    def __init__(self) -> None:
        # Completed bars stored as (open, high, low, close, volume, timestamp)
        self._bars: list[tuple[float, float, float, float, int, float]] = []
        # Current open bar
        self._bar_open: float | None = None
        self._bar_high: float = 0.0
        self._bar_low: float = float("inf")
        self._bar_close: float = 0.0
        self._bar_volume: int = 0
        self._bar_start_ts: float = 0.0
        self._tick_count: int = 0

    def on_tick(self, mid: float, ts: float | None = None) -> bool:
        """
        Ingest a tick.  Returns True when a new bar is completed.

        Parameters
        ----------
        mid : Mid price for this tick.
        ts  : Unix timestamp (seconds).  Defaults to ``time.time()``.
        """
        if ts is None:
            ts = time.time()

        self._tick_count += 1

        if self._bar_open is None:
            # Start the first bar
            self._bar_open = mid
            self._bar_high = mid
            self._bar_low = mid
            self._bar_close = mid
            self._bar_volume = 1
            self._bar_start_ts = ts
            return False

        # Update current bar
        self._bar_high = max(self._bar_high, mid)
        self._bar_low = min(self._bar_low, mid)
        self._bar_close = mid
        self._bar_volume += 1

        # Check if the bar period has elapsed
        if ts - self._bar_start_ts >= _BAR_PERIOD_S:
            self._bars.append((
                self._bar_open,
                self._bar_high,
                self._bar_low,
                self._bar_close,
                self._bar_volume,
                self._bar_start_ts,
            ))
            # Cap buffer length
            if len(self._bars) > _OHLCV_MAX_BARS:
                self._bars = self._bars[-_OHLCV_MAX_BARS:]
            # Open next bar
            self._bar_open = mid
            self._bar_high = mid
            self._bar_low = mid
            self._bar_close = mid
            self._bar_volume = 1
            self._bar_start_ts = ts
            return True

        return False

    @property
    def bar_count(self) -> int:
        """Number of completed bars in the buffer."""
        return len(self._bars)

    @property
    def tick_count(self) -> int:
        """Total ticks ingested."""
        return self._tick_count

    def dataframe(self) -> "Any":
        """
        Return a pandas DataFrame of completed bars with columns:
        open, high, low, close, volume, timestamp.

        Returns an empty DataFrame when no bars are complete yet.
        """
        import pandas as pd

        if not self._bars:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "timestamp"])

        rows = [
            {"open": o, "high": h, "low": lo, "close": c, "volume": v, "timestamp": ts}
            for o, h, lo, c, v, ts in self._bars
        ]
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df = df.set_index("timestamp")
        return df


# ─────────────────────────────────────────────────────────────────────────────
# InferenceEngine signal adapter — wraps ml.inference_engine for the tick loop
# ─────────────────────────────────────────────────────────────────────────────


class InferenceSignalAdapter:
    """
    Bridges the tick-based paper runner loop to the ML InferenceEngine.

    Maintains an OHLCVBuffer and calls InferenceEngine.predict() once per
    completed bar (not on every tick) to avoid redundant inference.  Signals
    are only emitted when confidence exceeds ``threshold``.

    The InferenceEngine is loaded lazily on first bar completion so startup
    is not blocked by model deserialization.
    """

    def __init__(self, symbol: str, threshold: float = _SIGNAL_THRESHOLD) -> None:
        self._symbol = symbol
        self._threshold = threshold
        self._buffer = OHLCVBuffer()
        self._engine: Any = None
        self._last_direction: str = "neutral"
        self._signal_count: int = 0

    def _get_engine(self) -> Any:
        """Lazy-load the InferenceEngine singleton."""
        if self._engine is None:
            try:
                from ml.inference_engine import get_inference_engine

                self._engine = get_inference_engine()
                logger.info(
                    "InferenceSignalAdapter: InferenceEngine loaded for %s", self._symbol
                )
            except Exception as exc:
                logger.warning(
                    "InferenceSignalAdapter: InferenceEngine unavailable (%s) — "
                    "signals will be neutral until model loads",
                    exc,
                )
        return self._engine

    def on_tick(self, mid: float, ts: float | None = None) -> dict[str, Any] | None:
        """
        Ingest a tick.  Returns a signal dict when a new bar completes AND
        the InferenceEngine produces a non-neutral signal above threshold.

        Returns None on every tick that does not complete a bar, or when the
        engine returns neutral / below-threshold confidence.
        """
        bar_completed = self._buffer.on_tick(mid, ts)

        if not bar_completed:
            return None

        if self._buffer.bar_count < _OHLCV_MIN_BARS:
            logger.debug(
                "InferenceSignalAdapter: warming up — %d/%d bars",
                self._buffer.bar_count,
                _OHLCV_MIN_BARS,
            )
            return None

        engine = self._get_engine()
        if engine is None:
            return None

        ohlcv_df = self._buffer.dataframe()
        try:
            result = engine.predict(ohlcv_df, symbol=self._symbol.replace("/", "_"))
        except Exception as exc:
            logger.warning("InferenceSignalAdapter: predict error: %s", exc)
            return None

        direction_raw = result.get("direction", "neutral")
        confidence = float(result.get("confidence", 0.0))

        if direction_raw == "neutral" or confidence < self._threshold:
            return None

        # Map InferenceEngine direction ("long"/"short") to order direction
        direction = "BUY" if direction_raw == "long" else "SELL"

        self._last_direction = direction
        self._signal_count += 1

        return {
            "type": "signal",
            "symbol": self._symbol,
            "direction": direction,
            "confidence": round(confidence, 4),
            "probability": round(float(result.get("probability", 0.5)), 4),
            "model_version": result.get("model_version", "unknown"),
            "bars_used": result.get("bars_used", self._buffer.bar_count),
            "mid": round(mid, 5),
            "tick_count": self._buffer.tick_count,
            "bar_count": self._buffer.bar_count,
            "latency_ms": round(float(result.get("latency_ms", 0.0)), 2),
            "fallback": result.get("fallback", False),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def status(self) -> dict[str, Any]:
        return {
            "symbol": self._symbol,
            "tick_count": self._buffer.tick_count,
            "bar_count": self._buffer.bar_count,
            "min_bars": _OHLCV_MIN_BARS,
            "warmed_up": self._buffer.bar_count >= _OHLCV_MIN_BARS,
            "last_direction": self._last_direction,
            "signal_count": self._signal_count,
            "threshold": self._threshold,
            "engine_loaded": self._engine is not None,
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
        trade_return = (price - mid) / mid * (1 if direction == "BUY" else -1) if mid > 0 and price > 0 else 0.0

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
      5. Polls OANDA REST for ticks, accumulates OHLCV bars, runs
         InferenceEngine (ml/inference_engine.py) for signal generation,
         and publishes order_request events to hopefx:order.
      6. Shuts down cleanly on SIGINT/SIGTERM or when _MAX_FILLS is reached.
    """

    def __init__(self) -> None:
        self._stop_event = asyncio.Event()
        self._signal_engine = InferenceSignalAdapter(symbol=_SYMBOL)
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
            "PaperRunner starting — symbol=%s units=%.0f threshold=%.2f "
            "max_fills=%d bar_period=%.0fs min_bars=%d engine=InferenceEngine",
            _SYMBOL,
            _ORDER_UNITS,
            _SIGNAL_THRESHOLD,
            _MAX_FILLS,
            _BAR_PERIOD_S,
            _OHLCV_MIN_BARS,
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
                now_ts = time.time()

                # Publish tick to event bus so other subscribers can use it
                await bus.publish_tick(
                    {
                        "symbol": _SYMBOL,
                        "bid": tick.get("bid", mid),
                        "ask": tick.get("ask", mid),
                        "mid": mid,
                        "timestamp": now_ts,
                        "source": "oanda_rest_poll",
                    }
                )

                # Run InferenceEngine signal adapter (returns signal only on bar completion)
                signal_dict = self._signal_engine.on_tick(mid, ts=now_ts)
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
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

        elapsed = time.monotonic() - self._t_start
        summary = self._fill_recorder.summary()
        router_metrics = self._router.metrics() if self._router else {}
        engine_status = self._signal_engine.status()

        logger.info(
            "PaperRunner session complete.\n"
            "  elapsed       : %.1f s\n"
            "  fills         : %d\n"
            "  orders        : %d\n"
            "  rejects       : %d\n"
            "  ticks         : %d\n"
            "  bars          : %d\n"
            "  signals       : %d\n"
            "  engine_loaded : %s\n"
            "  paper_mode    : %s",
            elapsed,
            summary["fill_count"],
            router_metrics.get("order_count", 0),
            router_metrics.get("reject_count", 0),
            engine_status.get("tick_count", 0),
            engine_status.get("bar_count", 0),
            engine_status.get("signal_count", 0),
            engine_status.get("engine_loaded", False),
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
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, _handle_signal, sig)

    await runner.run()


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
