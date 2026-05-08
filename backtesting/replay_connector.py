# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
backtesting/replay_connector.py
================================
Connects MarketReplayEngine (async tick generator) to BacktestEngine
(synchronous event loop) via a ReplayDataHandler adapter.

Also provides RegimeShiftStressTester — runs the backtest across multiple
historical stress regimes (COVID crash, rate shock, gold flash crash, etc.)
and reports per-regime performance metrics.

Architecture
------------
  MarketReplayEngine.replay_ticks()   ← async generator of GoldTick
        │
        ▼
  ReplayDataHandler.get_data()        ← synchronous iterator (bridges async→sync)
        │
        ▼
  BacktestEngine.run()                ← event-driven tick loop
        │
        ▼
  PerformanceMetrics                  ← Sharpe, drawdown, win rate, etc.

The async→sync bridge uses asyncio.run() on a pre-loaded tick buffer so
the BacktestEngine's synchronous loop can iterate without blocking.

Causal guarantee
----------------
MarketReplayEngine enforces strict timestamp ordering and passes every tick
through the same DQE + normalisation pipeline as live ticks. The connector
preserves this ordering — no look-ahead is possible.

Usage
-----
    from backtesting.replay_connector import ReplayBacktestRunner

    runner = ReplayBacktestRunner(
        strategy_fn=my_strategy,
        symbols=["XAU_USD"],
        initial_capital=10_000,
    )
    metrics = await runner.run(
        start=datetime(2020, 1, 1, tzinfo=timezone.utc),
        end=datetime(2020, 12, 31, tzinfo=timezone.utc),
    )
    logger.info(f"Sharpe: {metrics.sharpe_ratio:.2f}")

    # Regime-shift stress test across all built-in regimes:
    stress = RegimeShiftStressTester(strategy_fn=my_strategy)
    report = await stress.run_all_regimes()
    logger.info(stress.summary(report))
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

from pydantic import BaseModel

# FastAPI types imported at module level so `from __future__ import annotations`
# doesn't turn them into unresolvable forward references in endpoint signatures.
try:
    from fastapi import APIRouter, BackgroundTasks, HTTPException
except ImportError:  # pragma: no cover
    APIRouter = BackgroundTasks = HTTPException = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


# ── FastAPI request/response models (module-level so Pydantic can resolve refs) ──


class ReplayRunRequest(BaseModel):
    strategy: str = "momentum"
    symbol: str = "XAU_USD"
    start: str  # ISO date string, e.g. "2023-01-01"
    end: str
    initial_capital: float = 10_000.0


class StressRunRequest(BaseModel):
    strategy: str = "momentum"
    strategy_name: str = "unnamed"
    initial_capital: float = 10_000.0
    regime: str | None = None  # None = run all regimes


class ReplayJobStatus(BaseModel):
    job_id: str
    status: str
    result: dict | None = None


# ── Regime definitions ────────────────────────────────────────────────────────


class CreateSessionBody(BaseModel):
    """Request body for POST /api/replay/sessions."""

    symbol: str = "XAUUSD"
    timeframe: str = "H1"
    start_date: str = "2024-01-01"
    end_date: str = "2024-06-30"
    initial_equity: float = 10000.0


@dataclass
class StressRegime:
    """A named historical stress period for regime-shift testing."""

    name: str
    start: datetime
    end: datetime
    description: str
    expected_vol_mult: float  # expected vol relative to baseline (informational)


# Built-in stress regimes covering major market dislocations
STRESS_REGIMES: list[StressRegime] = [
    StressRegime(
        name="covid_crash_2020",
        start=datetime(2020, 2, 20, tzinfo=UTC),
        end=datetime(2020, 4, 30, tzinfo=UTC),
        description="COVID-19 market crash — extreme vol, liquidity crunch",
        expected_vol_mult=4.0,
    ),
    StressRegime(
        name="gold_flash_crash_2021",
        start=datetime(2021, 8, 9, tzinfo=UTC),
        end=datetime(2021, 8, 13, tzinfo=UTC),
        description="Gold flash crash — $100 drop in minutes, thin liquidity",
        expected_vol_mult=3.5,
    ),
    StressRegime(
        name="fed_rate_shock_2022",
        start=datetime(2022, 3, 1, tzinfo=UTC),
        end=datetime(2022, 6, 30, tzinfo=UTC),
        description="Fed 75bps hike cycle — USD surge, gold selloff",
        expected_vol_mult=2.5,
    ),
    StressRegime(
        name="ukraine_war_spike_2022",
        start=datetime(2022, 2, 24, tzinfo=UTC),
        end=datetime(2022, 3, 15, tzinfo=UTC),
        description="Russia-Ukraine war onset — gold safe-haven spike",
        expected_vol_mult=3.0,
    ),
    StressRegime(
        name="svb_banking_crisis_2023",
        start=datetime(2023, 3, 8, tzinfo=UTC),
        end=datetime(2023, 3, 31, tzinfo=UTC),
        description="SVB collapse — risk-off, gold bid, rate vol",
        expected_vol_mult=2.0,
    ),
    StressRegime(
        name="normal_baseline_2019",
        start=datetime(2019, 6, 1, tzinfo=UTC),
        end=datetime(2019, 8, 31, tzinfo=UTC),
        description="Normal market baseline — low vol, trending gold",
        expected_vol_mult=1.0,
    ),
]


# ── ReplayDataHandler — async→sync bridge ────────────────────────────────────


class ReplayDataHandler:
    """
    Synchronous data handler adapter for BacktestEngine.

    Bridges MarketReplayEngine's async tick generator to BacktestEngine's
    synchronous get_data() interface by pre-loading all ticks into memory
    via asyncio.run() before the backtest loop starts.

    Causal ordering is preserved — ticks are yielded in strict timestamp order.
    """

    def __init__(
        self,
        replay_engine: Any,
        symbol: str = "XAU_USD",
        speed: float = 0.0,  # 0 = as fast as possible (backtest mode)
    ) -> None:
        self._replay = replay_engine
        self._symbol = symbol
        self._speed = speed
        self._ticks: list[Any] = []  # pre-loaded GoldTick list

    def preload(
        self,
        start: datetime,
        end: datetime,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> int:
        """
        Pre-load all ticks for [start, end] into memory.

        Must be called before get_data(). Returns tick count.
        Uses the provided event loop or creates a new one.
        """

        async def _load():
            ticks = []
            async for tick in self._replay.replay_ticks(
                start=start,
                end=end,
                symbol=self._symbol,
                speed=0.0,  # always load at max speed
            ):
                ticks.append(tick)
            return ticks

        if loop is not None and loop.is_running():
            # We're inside an async context — use asyncio.ensure_future
            # and run synchronously via a thread-safe mechanism.
            # This path is used when called from an async test or runner.
            future = asyncio.run_coroutine_threadsafe(_load(), loop)
            self._ticks = future.result(timeout=300)
        else:
            self._ticks = asyncio.run(_load())

        logger.info(
            "ReplayDataHandler: pre-loaded %d ticks (%s → %s)",
            len(self._ticks),
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        )
        return len(self._ticks)

    def get_data(
        self,
        start_date: datetime,
        end_date: datetime,
        symbols: list[str],
    ) -> Iterator[tuple[datetime, str, Any]]:
        """
        Synchronous iterator yielding (timestamp, symbol, TickData) tuples.

        Called by BacktestEngine.run() on every bar/tick.
        Converts GoldTick → backtesting.engine.TickData.
        """
        from backtesting.engine import TickData

        for gold_tick in self._ticks:
            ts = getattr(gold_tick, "timestamp", None)
            if ts is None:
                continue
            if ts < start_date or ts > end_date:
                continue

            tick = TickData(
                timestamp=ts,
                symbol=getattr(gold_tick, "symbol", self._symbol),
                bid=float(getattr(gold_tick, "bid", 0.0)),
                ask=float(getattr(gold_tick, "ask", 0.0)),
                volume=float(getattr(gold_tick, "volume", 0.0)),
            )
            yield ts, tick.symbol, tick


# ── ReplayBacktestRunner ──────────────────────────────────────────────────────


class ReplayBacktestRunner:
    """
    Runs BacktestEngine with MarketReplayEngine as the data source.

    Handles the async→sync bridge, tick pre-loading, and result collection.
    """

    def __init__(
        self,
        strategy_fn: Callable,
        symbols: list[str] | None = None,
        initial_capital: float = 10_000.0,
        data_frequency: str = "tick",
        leverage: float = 1.0,
        replay_engine: Any | None = None,
    ) -> None:
        self._strategy_fn = strategy_fn
        self._symbols = symbols or ["XAU_USD"]
        self._initial_capital = initial_capital
        self._data_frequency = data_frequency
        self._leverage = leverage
        self._replay_engine = replay_engine

    async def run(
        self,
        start: datetime,
        end: datetime,
        symbol: str = "XAU_USD",
    ) -> Any:
        """
        Run a full backtest over [start, end] using Dukascopy tick data.

        Returns PerformanceMetrics from BacktestEngine.
        """
        from backtesting.engine import BacktestEngine, TransactionCostModel
        from data_layer.orchestrator import orchestrator as _orch

        MarketReplayEngine = type(_orch._replay)

        replay = self._replay_engine or MarketReplayEngine()
        handler = ReplayDataHandler(replay_engine=replay, symbol=symbol)

        # Pre-load ticks synchronously (runs async generator to completion)
        loop = asyncio.get_running_loop()
        tick_count = handler.preload(start, end, loop=loop)

        if tick_count == 0:
            logger.warning(
                "ReplayBacktestRunner: no ticks loaded for %s %s→%s",
                symbol,
                start.date(),
                end.date(),
            )
            return None

        engine = BacktestEngine(
            initial_capital=self._initial_capital,
            transaction_costs=TransactionCostModel(),
            data_frequency=self._data_frequency,
            leverage=self._leverage,
        )
        engine.set_strategy(self._strategy_fn, self._symbols)
        engine.set_data_handler(handler)

        logger.info(
            "ReplayBacktestRunner: running backtest %s→%s ticks=%d",
            start.date(),
            end.date(),
            tick_count,
        )
        metrics = engine.run(start, end)
        return metrics


# ── RegimeShiftStressTester ───────────────────────────────────────────────────


@dataclass
class RegimeResult:
    """Backtest result for a single stress regime."""

    regime: StressRegime
    metrics: Any  # PerformanceMetrics or None
    tick_count: int
    error: str | None = None

    @property
    def passed(self) -> bool:
        """True if the strategy survived the regime without blowing up."""
        if self.metrics is None:
            return False
        max_dd = getattr(self.metrics, "max_drawdown", 1.0)
        return max_dd < 0.20  # < 20% drawdown = survived

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        m = self.metrics
        return {
            "regime": {
                "name": self.regime.name,
                "start": self.regime.start.isoformat(),
                "end": self.regime.end.isoformat(),
                "description": self.regime.description,
                "expected_vol_mult": self.regime.expected_vol_mult,
            },
            "passed": self.passed,
            "tick_count": self.tick_count,
            "error": self.error,
            "metrics": {
                "sharpe_ratio": getattr(m, "sharpe_ratio", None),
                "max_drawdown": getattr(m, "max_drawdown", None),
                "total_return": getattr(m, "total_return", None),
                "win_rate": getattr(m, "win_rate", None),
                "total_trades": getattr(m, "total_trades", None),
            }
            if m is not None
            else None,
        }


@dataclass
class StressReport:
    """Full regime-shift stress test report."""

    strategy_name: str
    regimes_run: int
    regimes_passed: int
    regimes_failed: int
    results: list[RegimeResult]
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def worst_drawdown(self) -> float:
        dds = [getattr(r.metrics, "max_drawdown", 0.0) for r in self.results if r.metrics is not None]
        return max(dds) if dds else 0.0

    def best_sharpe(self) -> float:
        sharpes = [getattr(r.metrics, "sharpe_ratio", 0.0) for r in self.results if r.metrics is not None]
        return max(sharpes) if sharpes else 0.0

    def worst_sharpe(self) -> float:
        sharpes = [getattr(r.metrics, "sharpe_ratio", 0.0) for r in self.results if r.metrics is not None]
        return min(sharpes) if sharpes else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict for API responses and audit logs."""
        return {
            "strategy_name": self.strategy_name,
            "generated_at": self.generated_at,
            "regimes_run": self.regimes_run,
            "regimes_passed": self.regimes_passed,
            "regimes_failed": self.regimes_failed,
            "worst_drawdown": self.worst_drawdown(),
            "best_sharpe": self.best_sharpe(),
            "worst_sharpe": self.worst_sharpe(),
            "results": [r.to_dict() for r in self.results],
        }


class RegimeShiftStressTester:
    """
    Runs a strategy across all built-in stress regimes using real tick data.

    Each regime is a distinct historical period with known market character
    (crash, spike, trending, mean-reverting). The strategy must survive all
    regimes without exceeding the max_drawdown threshold.
    """

    def __init__(
        self,
        strategy_fn: Callable,
        strategy_name: str = "unnamed",
        initial_capital: float = 10_000.0,
        regimes: list[StressRegime] | None = None,
        replay_engine: Any | None = None,
        max_drawdown_threshold: float = 0.20,
    ) -> None:
        self._strategy_fn = strategy_fn
        self._strategy_name = strategy_name
        self._initial_capital = initial_capital
        self._regimes = regimes or STRESS_REGIMES
        self._replay_engine = replay_engine
        self._max_dd_thresh = max_drawdown_threshold

    async def run_all_regimes(self) -> StressReport:
        """
        Run the strategy across all stress regimes sequentially.

        Returns StressReport with per-regime metrics.
        """
        results: list[RegimeResult] = []

        for regime in self._regimes:
            logger.info(
                "RegimeShiftStressTester: running regime=%s (%s → %s)",
                regime.name,
                regime.start.date(),
                regime.end.date(),
            )
            result = await self._run_regime(regime)
            results.append(result)

            icon = "✓" if result.passed else "✗"
            dd = getattr(result.metrics, "max_drawdown", None)
            sr = getattr(result.metrics, "sharpe_ratio", None)
            logger.info(
                "  [%s] %s: ticks=%d dd=%.1f%% sharpe=%.2f%s",
                icon,
                regime.name,
                result.tick_count,
                (dd or 0) * 100,
                sr or 0,
                f" ERROR: {result.error}" if result.error else "",
            )

        passed = sum(1 for r in results if r.passed)
        report = StressReport(
            strategy_name=self._strategy_name,
            regimes_run=len(results),
            regimes_passed=passed,
            regimes_failed=len(results) - passed,
            results=results,
        )
        logger.info(
            "RegimeShiftStressTester: %d/%d regimes passed worst_dd=%.1f%% best_sharpe=%.2f worst_sharpe=%.2f",
            passed,
            len(results),
            report.worst_drawdown() * 100,
            report.best_sharpe(),
            report.worst_sharpe(),
        )
        return report

    async def _run_regime(self, regime: StressRegime) -> RegimeResult:
        """Run a single regime. Returns RegimeResult."""
        runner = ReplayBacktestRunner(
            strategy_fn=self._strategy_fn,
            initial_capital=self._initial_capital,
            replay_engine=self._replay_engine,
        )
        try:
            metrics = await runner.run(
                start=regime.start,
                end=regime.end,
                symbol="XAU_USD",
            )
            # Count ticks from the handler (approximate from metrics)
            tick_count = getattr(metrics, "total_trades", 0) if metrics else 0
            return RegimeResult(
                regime=regime,
                metrics=metrics,
                tick_count=tick_count,
            )
        except Exception as exc:
            logger.error(
                "RegimeShiftStressTester: regime=%s failed: %s",
                regime.name,
                exc,
            )
            return RegimeResult(
                regime=regime,
                metrics=None,
                tick_count=0,
                error="Regime simulation failed — check server logs",
            )

    async def run_single_regime(self, regime_name: str) -> RegimeResult:
        """
        Run the strategy against a single named stress regime.

        Args:
            regime_name: Must match one of the ``name`` fields in
                ``self._regimes`` (e.g. ``"covid_crash_2020"``).

        Returns:
            RegimeResult for the requested regime.

        Raises:
            ValueError: If *regime_name* is not found in the configured regimes.
        """
        regime = next((r for r in self._regimes if r.name == regime_name), None)
        if regime is None:
            available = [r.name for r in self._regimes]
            raise ValueError(f"Regime '{regime_name}' not found. Available: {available}")
        logger.info(
            "RegimeShiftStressTester: running single regime=%s (%s → %s)",
            regime.name,
            regime.start.date(),
            regime.end.date(),
        )
        return await self._run_regime(regime)

    def summary(self, report: StressReport) -> str:
        """Return a human-readable summary of the stress report."""
        lines = [
            f"REGIME-SHIFT STRESS TEST — {report.strategy_name}",
            f"Generated: {report.generated_at}",
            f"Regimes: {report.regimes_run}  Passed: {report.regimes_passed}  Failed: {report.regimes_failed}",
            f"Worst drawdown: {report.worst_drawdown():.1%}  "
            f"Sharpe range: [{report.worst_sharpe():.2f}, {report.best_sharpe():.2f}]",
            "",
        ]
        for r in report.results:
            icon = "✓" if r.passed else "✗"
            dd = getattr(r.metrics, "max_drawdown", None)
            sr = getattr(r.metrics, "sharpe_ratio", None)
            ret = getattr(r.metrics, "total_return", None)
            lines.append(
                f"  [{icon}] {r.regime.name:<35} "
                f"dd={f'{dd:.1%}' if dd is not None else 'N/A':>7}  "
                f"sharpe={f'{sr:.2f}' if sr is not None else 'N/A':>6}  "
                f"return={f'{ret:.1%}' if ret is not None else 'N/A':>7}"
            )
            if r.error:
                lines.append(f"       ERROR: {r.error}")
        return "\n".join(lines)


# ── FastAPI router ────────────────────────────────────────────────────────────


def create_replay_router():
    """
    FastAPI router for replay backtest and regime-shift stress test endpoints.

    Mount with::

        from backtesting.replay_connector import create_replay_router
        app.include_router(create_replay_router())
    """
    router = APIRouter(prefix="/api/replay", tags=["Replay Backtest"])
    _jobs: dict[str, Any] = {}

    # ── Session-based bar-by-bar replay ──────────────────────────────────────
    # Sessions are stored in-memory (Redis if available) and support step/run.
    import json as _json
    import uuid as _uuid

    _SESSIONS: dict[str, dict] = {}

    def _redis_client():
        try:
            import redis as _r
            import os
            c = _r.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                            socket_connect_timeout=1, socket_timeout=1)
            c.ping()
            return c
        except Exception:
            return None

    def _save_session(sess: dict) -> None:
        _SESSIONS[sess["session_id"]] = sess
        rc = _redis_client()
        if rc:
            try:
                rc.setex(f"hopefx:replay:{sess['session_id']}", 86400, _json.dumps(sess))
            except Exception:  # nosec B110
                pass

    def _load_session(sid: str) -> dict | None:
        if sid in _SESSIONS:
            return _SESSIONS[sid]
        rc = _redis_client()
        if rc:
            try:
                raw = rc.get(f"hopefx:replay:{sid}")
                if raw:
                    sess = _json.loads(raw)
                    _SESSIONS[sid] = sess
                    return sess
            except Exception:  # nosec B110
                pass
        return None

    def _list_sessions() -> list[dict]:
        rc = _redis_client()
        if rc:
            try:
                keys = rc.keys("hopefx:replay:*")
                sessions = []
                for k in keys:
                    raw = rc.get(k)
                    if raw:
                        sessions.append(_json.loads(raw))
                return sessions
            except Exception:  # nosec B110
                pass
        return list(_SESSIONS.values())

    def _delete_session(sid: str) -> None:
        _SESSIONS.pop(sid, None)
        rc = _redis_client()
        if rc:
            try:
                rc.delete(f"hopefx:replay:{sid}")
            except Exception:  # nosec B110
                pass

    def _build_bars(symbol: str, timeframe: str, start_date: str, end_date: str) -> list[dict]:
        """Load OHLCV bars from the data layer or generate synthetic bars."""
        import math
        import random
        from datetime import datetime, timedelta

        try:
            from brokers.ohlcv_store import OHLCVStore
            store = OHLCVStore()
            bars_raw = store.get_bars(symbol, timeframe, start_date, end_date)
            if bars_raw:
                return [
                    {
                        "time": int(b["timestamp"].timestamp()) if hasattr(b.get("timestamp", 0), "timestamp") else int(b.get("time", 0)),
                        "open": float(b["open"]),
                        "high": float(b["high"]),
                        "low": float(b["low"]),
                        "close": float(b["close"]),
                        "volume": float(b.get("volume", 0)),
                    }
                    for b in bars_raw
                ]
        except Exception:  # nosec B110
            pass

        # Synthetic fallback — realistic random walk
        SEED_PRICES = {
            "XAUUSD": 2000.0, "EURUSD": 1.08, "GBPUSD": 1.27,
            "USDJPY": 150.0, "BTCUSD": 45000.0, "US30": 38000.0, "NAS100": 17000.0,
        }
        TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
        price = SEED_PRICES.get(symbol, 1.0)
        vol = price * 0.001
        tf_min = TF_MINUTES.get(timeframe, 60)

        try:
            dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
        except ValueError:
            dt = datetime(2024, 1, 1)
            end_dt = datetime(2024, 6, 30)

        bars = []
        rng = random.Random(42)
        while dt <= end_dt:
            o = price
            change = rng.gauss(0, vol)
            c = max(o + change, o * 0.001)
            h = max(o, c) + abs(rng.gauss(0, vol * 0.5))
            l = min(o, c) - abs(rng.gauss(0, vol * 0.5))
            bars.append({
                "time": int(dt.timestamp()),
                "open": round(o, 5),
                "high": round(h, 5),
                "low": round(l, 5),
                "close": round(c, 5),
                "volume": round(abs(rng.gauss(1000, 300)), 0),
            })
            price = c
            dt += timedelta(minutes=tf_min)
            if len(bars) >= 2000:
                break

        return bars

    @router.get("/sessions", summary="List replay sessions")
    async def list_replay_sessions():
        sessions = _list_sessions()
        # Strip bars from list view for performance
        slim = [{k: v for k, v in s.items() if k != "bars"} for s in sessions]
        return {"sessions": slim}

    @router.post("/sessions", summary="Create a replay session")
    async def create_replay_session(body: CreateSessionBody):
        sid = str(_uuid.uuid4())[:12]
        bars = _build_bars(body.symbol, body.timeframe, body.start_date, body.end_date)
        sess = {
            "session_id": sid,
            "symbol": body.symbol,
            "timeframe": body.timeframe,
            "start_date": body.start_date,
            "end_date": body.end_date,
            "current_bar": 0,
            "total_bars": len(bars),
            "status": "created",
            "current_price": bars[0]["close"] if bars else 0.0,
            "equity": body.initial_equity,
            "initial_equity": body.initial_equity,
            "pnl": 0.0,
            "trades": [],
            "bars": bars,
            "created_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        }
        _save_session(sess)
        return sess

    @router.get("/sessions/{session_id}", summary="Get replay session state")
    async def get_replay_session(session_id: str):
        sess = _load_session(session_id)
        if not sess:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        return sess

    @router.post("/sessions/{session_id}/step", summary="Advance one bar")
    async def step_replay_session(session_id: str):
        sess = _load_session(session_id)
        if not sess:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        if sess["status"] == "completed":
            return sess
        bars = sess.get("bars", [])
        next_bar = sess["current_bar"] + 1
        if next_bar >= len(bars):
            sess["status"] = "completed"
            sess["current_bar"] = len(bars)
        else:
            sess["current_bar"] = next_bar
            sess["current_price"] = bars[next_bar]["close"]
            sess["status"] = "running"
        _save_session(sess)
        return sess

    @router.post("/sessions/{session_id}/run", summary="Advance N bars")
    async def run_replay_session(session_id: str, bars: int = 10):
        sess = _load_session(session_id)
        if not sess:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        if sess["status"] == "completed":
            return sess
        all_bars = sess.get("bars", [])
        target = min(sess["current_bar"] + bars, len(all_bars))
        if target >= len(all_bars):
            sess["status"] = "completed"
            sess["current_bar"] = len(all_bars)
        else:
            sess["current_bar"] = target
            sess["current_price"] = all_bars[target]["close"]
            sess["status"] = "running"
        _save_session(sess)
        return sess

    @router.delete("/sessions/{session_id}", status_code=204, summary="Delete a replay session")
    async def delete_replay_session(session_id: str):
        _delete_session(session_id)
        return None

    # Use module-level models (ReplayRunRequest, StressRunRequest, ReplayJobStatus)
    # so Pydantic v2 can resolve forward references when building the OpenAPI schema.
    JobStatus = ReplayJobStatus

    def _resolve_strategy(name: str) -> Any:
        """Resolve a strategy name to a callable."""
        _MAP = {
            "momentum": ("strategies.momentum", "MomentumStrategy"),
            "rsi": ("strategies.rsi_strategy", "RSIStrategy"),
            "macd": ("strategies.macd_strategy", "MACDStrategy"),
            "ma_crossover": ("strategies.ma_crossover", "MovingAverageCrossover"),
        }
        if name not in _MAP:
            raise ValueError(f"Unknown strategy '{name}'. Available: {list(_MAP)}")
        import importlib

        mod_path, cls_name = _MAP[name]
        mod = importlib.import_module(mod_path)
        return getattr(mod, cls_name)

    @router.get("/regimes", summary="List available stress regimes")
    async def list_regimes():
        return {
            "regimes": [
                {
                    "name": r.name,
                    "start": r.start.isoformat(),
                    "end": r.end.isoformat(),
                    "description": r.description,
                    "expected_vol_mult": r.expected_vol_mult,
                }
                for r in STRESS_REGIMES
            ]
        }

    @router.post("/stress", response_model=JobStatus, summary="Run regime-shift stress test")
    async def run_stress(req: StressRunRequest, background_tasks: BackgroundTasks):
        import uuid

        job_id = str(uuid.uuid4())[:8]
        _jobs[job_id] = {"status": "running", "result": None}

        async def _run():
            try:
                strategy_cls = _resolve_strategy(req.strategy)
                tester = RegimeShiftStressTester(
                    strategy_fn=strategy_cls,
                    strategy_name=req.strategy_name,
                    initial_capital=req.initial_capital,
                )
                if req.regime:
                    result = await tester.run_single_regime(req.regime)
                    _jobs[job_id] = {"status": "completed", "result": result.to_dict()}
                else:
                    report = await tester.run_all_regimes()
                    _jobs[job_id] = {"status": "completed", "result": report.to_dict()}
            except Exception as exc:
                logger.exception("Stress test job %s failed", job_id)
                _jobs[job_id] = {"status": "error", "result": {"error": str(exc)}}

        background_tasks.add_task(_run)
        return JobStatus(job_id=job_id, status="running")

    @router.get("/stress/{job_id}", response_model=JobStatus)
    async def get_stress_status(job_id: str):
        if job_id not in _jobs:
            raise HTTPException(404, f"Job {job_id} not found")
        job = _jobs[job_id]
        return JobStatus(job_id=job_id, status=job["status"], result=job["result"])

    return router
