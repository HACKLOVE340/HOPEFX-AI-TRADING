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
    print(f"Sharpe: {metrics.sharpe_ratio:.2f}")

    # Regime-shift stress test across all built-in regimes:
    stress = RegimeShiftStressTester(strategy_fn=my_strategy)
    report = await stress.run_all_regimes()
    print(stress.summary(report))
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any
from collections.abc import Callable, Iterator

logger = logging.getLogger(__name__)


# ── Regime definitions ────────────────────────────────────────────────────────


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
        loop = asyncio.get_event_loop()
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
                error=str(exc),
            )

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
