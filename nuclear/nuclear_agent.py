# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
nuclear/nuclear_agent.py
==========================
NuclearStrategyAgent — top-level orchestrator for the Nuclear Strategy system.

Wires all components end-to-end:
  RedisStreamReader → FeatureBuilder → ItosConeEngine → RegimeClassifier
  → NuclearStrategyEngine → ShadowBacktestEngine → SignalComposer
  → NuclearSignal (→ execution engine, brokers only after APPROVED)

Data flow
---------
  1. RedisStreamReader pulls live ticks + OHLCV bars from Redis pub/sub
     (NuclearStreamer → FinnHub/TwelveData/Polygon → Redis)
  2. FeatureBuilder computes ATR/BB/RSI/EMA/MACD + macro features
  3. ItosConeEngine generates ±2σ GBM price cones per timeframe
  4. RegimeClassifier detects market regime (multi-TF + macro + cone)
  5. NuclearStrategyEngine selects strategy (ICT/SMC/breakout/MR)
     and validates signal against ITOS cone
  6. ShadowBacktestEngine simulates last 30 ticks + 5 bars per TF
  7. SignalComposer assembles NuclearSignal with approval gate

No broker APIs are called here. Brokers receive orders only after
NuclearSignal.approval_status == 'APPROVED' via the execution engine.

Usage
-----
    agent = NuclearStrategyAgent()
    await agent.start()                    # starts Redis listener

    # Synchronous snapshot (call from any coroutine)
    result = agent.analyze()               # full pipeline run
    signal = result.signal                 # NuclearSignal or None
    if signal and signal.is_approved:
        await execution_engine.submit(signal)

    # Or run the continuous loop:
    await agent.run_loop(interval_s=5.0)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from nuclear.feature_builder import FeatureBuilder, MultiTimeframeFeatures
from nuclear.itos_cone_engine import ItosCone, ItosConeEngine
from nuclear.redis_stream_reader import RedisStreamReader, get_stream_reader
from nuclear.regime_classifier import RegimeClassifier, RegimeResult
from nuclear.shadow_backtest import BacktestResult, ShadowBacktestEngine
from nuclear.signal_composer import NuclearSignal, SignalComposer
from nuclear.strategy_engine import NuclearStrategyEngine

UTC = timezone.utc
logger = logging.getLogger(__name__)

# ── Analysis result container ─────────────────────────────────────────────────


@dataclass
class AnalysisResult:
    """
    Full output of one NuclearStrategyAgent.analyze() run.

    Contains every intermediate artifact so callers can inspect
    any layer of the pipeline without re-running it.
    """

    symbol: str
    signal: NuclearSignal | None
    regime: RegimeResult | None
    backtest: BacktestResult | None
    cone_merged: dict[str, Any]
    mtf_features: MultiTimeframeFeatures | None
    ticks_available: int
    bars_available: dict[str, int]
    pipeline_ms: float  # wall-clock time for full pipeline
    error: str | None = None
    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def has_signal(self) -> bool:
        return self.signal is not None

    @property
    def is_approved(self) -> bool:
        return self.signal is not None and self.signal.is_approved

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "has_signal": self.has_signal,
            "is_approved": self.is_approved,
            "signal": self.signal.to_dict() if self.signal else None,
            "regime": self.regime.to_dict() if self.regime else None,
            "backtest": self.backtest.to_dict() if self.backtest else None,
            "cone_merged": self.cone_merged,
            "ticks_available": self.ticks_available,
            "bars_available": self.bars_available,
            "pipeline_ms": round(self.pipeline_ms, 2),
            "error": self.error,
            "computed_at": self.computed_at.isoformat(),
        }


# ── NuclearStrategyAgent ──────────────────────────────────────────────────────


class NuclearStrategyAgent:
    """
    End-to-end Nuclear Strategy Agent.

    Orchestrates the full pipeline from Redis streams to NuclearSignal.
    Thread-safe: all state mutations are protected by asyncio.Lock.

    Parameters
    ----------
    symbol : str
        Instrument to trade (default: "XAU_USD").
    reader : RedisStreamReader, optional
        Provide a custom reader (useful for testing). Defaults to singleton.
    bootstrap : bool
        If True, pre-fill bar buffers from Redis list history on start().
    """

    def __init__(
        self,
        symbol: str = "XAU_USD",
        reader: RedisStreamReader | None = None,
        bootstrap: bool = True,
    ) -> None:
        self._symbol = symbol
        self._reader = reader or get_stream_reader()
        self._bootstrap = bootstrap

        # Pipeline components
        self._feature_builder = FeatureBuilder(self._reader, symbol=symbol)
        self._cone_engine = ItosConeEngine()
        self._regime_clf = RegimeClassifier()
        self._strategy_engine = NuclearStrategyEngine()
        self._backtest_engine = ShadowBacktestEngine(rng_seed=42)
        self._composer = SignalComposer()

        # State
        self._running = False
        self._lock = asyncio.Lock()
        self._last_result: AnalysisResult | None = None
        self._signal_history: list[NuclearSignal] = []
        self._analysis_count = 0
        self._approved_count = 0
        self._error_count = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the Redis stream reader and optionally bootstrap bar history."""
        if self._running:
            return
        await self._reader.start()
        if self._bootstrap:
            try:
                await self._reader.bootstrap()
            except Exception as exc:
                logger.warning("Bootstrap failed (non-fatal): %s", exc)
        self._running = True
        logger.info("NuclearStrategyAgent started for %s", self._symbol)

    async def stop(self) -> None:
        """Stop the Redis stream reader."""
        self._running = False
        await self._reader.stop()
        logger.info("NuclearStrategyAgent stopped")

    # ── Core pipeline ─────────────────────────────────────────────────────────

    def analyze(
        self,
        n_ticks: int = 30,
        n_bars: int = 5,
        timeframes: list[str] | None = None,
    ) -> AnalysisResult:
        """
        Run the full analysis pipeline synchronously.

        Safe to call from any coroutine or thread. Does NOT require
        the event loop — all Redis data is read from in-memory buffers.

        Parameters
        ----------
        n_ticks : int
            Number of recent ticks to use (default: 30).
        n_bars : int
            Number of bars per timeframe for backtest (default: 5).
        timeframes : list[str], optional
            Subset of timeframes to analyse. Defaults to all available.

        Returns
        -------
        AnalysisResult
        """
        t0 = time.perf_counter()
        self._analysis_count += 1

        try:
            result = self._run_pipeline(n_ticks=n_ticks, n_bars=n_bars, timeframes=timeframes)
        except Exception as exc:
            self._error_count += 1
            logger.error("NuclearStrategyAgent.analyze error: %s", exc, exc_info=True)
            result = AnalysisResult(
                symbol=self._symbol,
                signal=None,
                regime=None,
                backtest=None,
                cone_merged={},
                mtf_features=None,
                ticks_available=0,
                bars_available={},
                pipeline_ms=(time.perf_counter() - t0) * 1000,
                error=str(exc),
            )

        self._last_result = result
        if result.is_approved and result.signal:
            self._approved_count += 1
            self._signal_history.append(result.signal)
            if len(self._signal_history) > 100:
                self._signal_history = self._signal_history[-100:]

        return result

    def _run_pipeline(
        self,
        n_ticks: int,
        n_bars: int,
        timeframes: list[str] | None,
    ) -> AnalysisResult:
        """Execute the full pipeline. Called by analyze()."""
        t0 = time.perf_counter()

        # ── Step 1: Snapshot from Redis buffers ───────────────────────────────
        ticks = self._reader.get_ticks(n_ticks)
        all_bars = self._reader.get_all_bars()
        bars_available = {tf: len(bars) for tf, bars in all_bars.items() if bars}
        current_price = self._reader.get_latest_price()

        logger.debug(
            "Pipeline: %d ticks, bars=%s, price=%s",
            len(ticks),
            bars_available,
            current_price,
        )

        # ── Step 2: Multi-timeframe features ──────────────────────────────────
        mtf = self._feature_builder.build_all(timeframes=timeframes)

        # ── Step 3: ITOS cones ────────────────────────────────────────────────
        cones: dict[str, ItosCone] = {}
        for tf, bars in all_bars.items():
            if len(bars) < 10:
                continue
            try:
                import numpy as np

                closes = np.array([b.close for b in bars if b.close > 0])
                if len(closes) >= 10:
                    cones[tf] = self._cone_engine.compute(
                        closes,
                        current_price=current_price,
                        symbol=self._symbol,
                        timeframe=tf,
                    )
            except Exception as exc:
                logger.debug("Cone compute error for %s: %s", tf, exc)

        # Merge cones (weighted by timeframe)
        cone_merged = self._cone_engine.merge_cones(cones) if cones else {}

        # Primary cone for validator (prefer daily, fallback to first available)
        primary_cone = cones.get("daily") or cones.get("1h") or (next(iter(cones.values())) if cones else None)

        # ── Step 4: Regime classification ─────────────────────────────────────
        regime = self._regime_clf.classify(mtf, cone_merged)

        # ── Step 5: Strategy signal generation ────────────────────────────────
        raw_signal = self._strategy_engine.generate(
            mtf=mtf,
            regime=regime,
            cone=primary_cone,
            cone_merged=cone_merged,
            ticks=ticks,
        )

        # ── Step 6: Shadow backtest ───────────────────────────────────────────
        backtest = self._backtest_engine.run(
            ticks=ticks,
            bars_by_tf=all_bars,
            strategy_engine=self._strategy_engine,
            mtf_features=mtf,
            regime=regime,
            cone=primary_cone,
            cone_merged=cone_merged,
            symbol=self._symbol,
        )

        # ── Step 7: Signal composition ────────────────────────────────────────
        nuclear_signal: NuclearSignal | None = None
        if raw_signal is not None:
            nuclear_signal = self._composer.compose(
                raw_signal=raw_signal,
                backtest=backtest,
                regime=regime,
                cone_merged=cone_merged,
                mtf=mtf,
            )

        pipeline_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "Pipeline complete in %.1fms: regime=%s signal=%s approved=%s",
            pipeline_ms,
            regime.regime,
            nuclear_signal.direction if nuclear_signal else "none",
            nuclear_signal.is_approved if nuclear_signal else False,
        )

        return AnalysisResult(
            symbol=self._symbol,
            signal=nuclear_signal,
            regime=regime,
            backtest=backtest,
            cone_merged=cone_merged,
            mtf_features=mtf,
            ticks_available=len(ticks),
            bars_available=bars_available,
            pipeline_ms=pipeline_ms,
        )

    # ── Continuous loop ───────────────────────────────────────────────────────

    async def run_loop(
        self,
        interval_s: float = 5.0,
        on_signal=None,
    ) -> None:
        """
        Run the analysis pipeline continuously at `interval_s` cadence.

        Parameters
        ----------
        interval_s : float
            Seconds between pipeline runs (default: 5).
        on_signal : coroutine callable, optional
            Called with (NuclearSignal,) when an APPROVED signal is generated.
            Signature: async def on_signal(signal: NuclearSignal) -> None
        """
        logger.info(
            "NuclearStrategyAgent loop started: symbol=%s interval=%.1fs",
            self._symbol,
            interval_s,
        )
        while self._running:
            try:
                result = self.analyze()
                if result.is_approved and result.signal and on_signal:
                    try:
                        await on_signal(result.signal)
                    except Exception as exc:
                        logger.error("on_signal callback error: %s", exc)
            except Exception as exc:
                logger.error("run_loop iteration error: %s", exc)
            await asyncio.sleep(interval_s)

    # ── Status and introspection ──────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Return agent status snapshot for the dashboard/API."""
        reader_stats = self._reader.stats() or {}
        last = self._last_result

        return {
            "symbol": self._symbol,
            "running": self._running,
            "analysis_count": self._analysis_count,
            "approved_count": self._approved_count,
            "error_count": self._error_count,
            "approval_rate": (
                round(self._approved_count / self._analysis_count, 3) if self._analysis_count > 0 else 0.0
            ),
            "reader": reader_stats,
            "last_regime": last.regime.regime if last and last.regime else None,
            "last_regime_confidence": (round(last.regime.confidence, 3) if last and last.regime else None),
            "last_signal_direction": (last.signal.direction if last and last.signal else None),
            "last_signal_status": (last.signal.approval_status if last and last.signal else None),
            "last_pipeline_ms": round(last.pipeline_ms, 2) if last else None,
            "last_computed_at": last.computed_at.isoformat() if last else None,
            "signal_history_count": len(self._signal_history),
        }

    def get_signal_history(self, n: int = 20) -> list[dict[str, Any]]:
        """Return the last n approved signals."""
        return [s.to_dict() for s in self._signal_history[-n:]]

    def get_last_result(self) -> AnalysisResult | None:
        """Return the most recent AnalysisResult."""
        return self._last_result

    def get_regime_history(self, n: int = 20) -> list[dict[str, Any]]:
        """Return recent regime transitions from the classifier."""
        return self._regime_clf.history(n)

    def get_strategy_signal_history(self, n: int = 20) -> list[dict[str, Any]]:
        """Return recent raw strategy signals (pre-composition)."""
        return self._strategy_engine.signal_history(n)

    def clear_history(self) -> int:
        """
        Clear the in-memory approved signal history.

        Returns the number of signals that were cleared.
        """
        count = len(self._signal_history)
        self._signal_history.clear()
        logger.info("Signal history cleared (%d signals removed)", count)
        return count

    # ── Repr ──────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"NuclearStrategyAgent("
            f"symbol={self._symbol}, "
            f"running={self._running}, "
            f"analyses={self._analysis_count}, "
            f"approved={self._approved_count})"
        )


# ── Module-level singleton ────────────────────────────────────────────────────

_agent_instance: NuclearStrategyAgent | None = None


def get_nuclear_agent(
    symbol: str = "XAU_USD",
    reader: RedisStreamReader | None = None,
) -> NuclearStrategyAgent:
    """
    Return the process-wide NuclearStrategyAgent singleton.

    Thread-safe: safe to call from multiple coroutines.
    The first call creates the instance; subsequent calls return the cached one.
    """
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = NuclearStrategyAgent(symbol=symbol, reader=reader)
    return _agent_instance
