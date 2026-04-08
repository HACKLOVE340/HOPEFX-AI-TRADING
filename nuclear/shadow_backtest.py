# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
nuclear/shadow_backtest.py
============================
Shadow backtest engine for the Nuclear Strategy Agent.

Simulates the full signal → fill → P&L pipeline on historical Redis data
without touching any broker. Runs in "shadow mode" alongside live trading.

Simulation spec
---------------
- Last 30 ticks from ticks_channel (tick-level simulation)
- Last 5 bars across ALL timeframes (1m/5m/30m/1h/daily/weekly/monthly/yearly)
- Realistic fill model: mid ± half_spread + market_impact
- Per-trade P&L, cumulative equity curve, drawdown
- Sharpe ratio, win rate, profit factor, max drawdown

No broker APIs. All data from RedisStreamReader ring buffers.

Usage
-----
    from nuclear.shadow_backtest import ShadowBacktestEngine

    engine = ShadowBacktestEngine()
    result = engine.run(
        ticks=reader.get_ticks(30),
        bars_by_tf=reader.get_all_bars(),
        strategy_engine=nuclear_engine,
        mtf_features=mtf,
        regime=regime_result,
        cone=cone,
        cone_merged=cone_merged,
    )
    logger.info(result.sharpe, result.win_rate, result.max_drawdown_pct)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np

from nuclear.feature_builder import MultiTimeframeFeatures, build_features_from_bars
from nuclear.itos_cone_engine import ItosCone, ItosConeEngine
from nuclear.redis_stream_reader import OHLCVBar, TickSnapshot
from nuclear.regime_classifier import RegimeClassifier, RegimeResult
from nuclear.strategy_engine import (
    FLAT,
    LONG,
    NuclearStrategyEngine,
)

UTC = timezone.utc
logger = logging.getLogger(__name__)

# ── Slippage model parameters ─────────────────────────────────────────────────
_HALF_SPREAD_BPS = 3.0  # 0.3 pip half-spread
_IMPACT_BPS = 1.5  # market impact
_NOISE_BPS = 0.5  # random noise
_COMMISSION_PER_LOT = 7.0  # USD per lot round-trip

# Minimum bars per timeframe for a valid backtest window
_MIN_BARS_PER_TF = 5


@dataclass
class ShadowTrade:
    """A single simulated trade in the shadow backtest."""

    trade_id: int
    direction: str
    strategy: str
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    entry_time: datetime
    exit_time: datetime
    exit_reason: str  # "tp1" / "sl" / "timeout" / "signal_flip"
    pnl_pips: float  # price units
    pnl_pct: float  # % of entry price
    confidence: float
    regime: str
    timeframe: str
    cone_aligned: bool

    @property
    def is_winner(self) -> bool:
        return self.pnl_pips > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "direction": self.direction,
            "strategy": self.strategy,
            "entry_price": round(self.entry_price, 4),
            "exit_price": round(self.exit_price, 4),
            "stop_loss": round(self.stop_loss, 4),
            "take_profit": round(self.take_profit, 4),
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat(),
            "exit_reason": self.exit_reason,
            "pnl_pips": round(self.pnl_pips, 4),
            "pnl_pct": round(self.pnl_pct, 6),
            "is_winner": self.is_winner,
            "confidence": round(self.confidence, 3),
            "regime": self.regime,
            "timeframe": self.timeframe,
            "cone_aligned": self.cone_aligned,
        }


@dataclass
class BacktestResult:
    """Aggregated results from a shadow backtest run."""

    symbol: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown_pct: float
    total_pnl_pct: float
    avg_pnl_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    best_trade_pct: float
    worst_trade_pct: float
    avg_rr: float  # average realised risk/reward
    cone_aligned_win_rate: float  # win rate for cone-aligned trades only
    trades: list[ShadowTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    timeframes_tested: list[str] = field(default_factory=list)
    ticks_tested: int = 0
    regime_breakdown: dict[str, int] = field(default_factory=dict)
    strategy_breakdown: dict[str, int] = field(default_factory=dict)
    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def confidence_score(self) -> float:
        """
        Overall backtest confidence score [0, 1].

        Combines win rate, Sharpe, profit factor, and sample size.
        Used by the signal composer to weight live signal confidence.
        """
        if self.total_trades == 0:
            return 0.0
        sample_score = min(self.total_trades / 20.0, 1.0)
        wr_score = self.win_rate
        sharpe_score = min(max(self.sharpe_ratio / 2.0, 0.0), 1.0)
        pf_score = min(max((self.profit_factor - 1.0) / 2.0, 0.0), 1.0)
        return round(
            0.25 * sample_score + 0.35 * wr_score + 0.25 * sharpe_score + 0.15 * pf_score,
            3,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 3),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "total_pnl_pct": round(self.total_pnl_pct, 4),
            "avg_pnl_pct": round(self.avg_pnl_pct, 6),
            "avg_win_pct": round(self.avg_win_pct, 6),
            "avg_loss_pct": round(self.avg_loss_pct, 6),
            "best_trade_pct": round(self.best_trade_pct, 6),
            "worst_trade_pct": round(self.worst_trade_pct, 6),
            "avg_rr": round(self.avg_rr, 3),
            "cone_aligned_win_rate": round(self.cone_aligned_win_rate, 4),
            "confidence_score": round(self.confidence_score, 3),
            "timeframes_tested": self.timeframes_tested,
            "ticks_tested": self.ticks_tested,
            "regime_breakdown": self.regime_breakdown,
            "strategy_breakdown": self.strategy_breakdown,
            "equity_curve": [round(e, 6) for e in self.equity_curve],
            "trades": [t.to_dict() for t in self.trades],
            "computed_at": self.computed_at.isoformat(),
        }


# ── ShadowBacktestEngine ──────────────────────────────────────────────────────


class ShadowBacktestEngine:
    """
    Simulates the Nuclear Strategy Engine on historical Redis data.

    Tick simulation
    ---------------
    For each of the last 30 ticks:
      1. Build a rolling feature snapshot from bars up to that tick
      2. Run regime classification
      3. Run strategy engine → raw signal
      4. Simulate fill with slippage model
      5. Simulate exit: SL hit, TP1 hit, or timeout at next tick

    Bar simulation
    --------------
    For each timeframe, walk through the last 5 bars:
      1. Build features from bars[:-i] (walk-forward)
      2. Generate signal on bar close
      3. Simulate next-bar fill and exit

    Both simulations contribute trades to the aggregate result.
    """

    def __init__(
        self,
        half_spread_bps: float = _HALF_SPREAD_BPS,
        impact_bps: float = _IMPACT_BPS,
        noise_bps: float = _NOISE_BPS,
        rng_seed: int | None = None,
    ) -> None:
        self._half_spread = half_spread_bps / 10_000
        self._impact = impact_bps / 10_000
        self._noise = noise_bps / 10_000
        self._rng = np.random.default_rng(rng_seed)
        self._clf = RegimeClassifier()
        self._cone_engine = ItosConeEngine()

    # ── Public API ────────────────────────────────────────────────────────────

    def run(
        self,
        ticks: list[TickSnapshot],
        bars_by_tf: dict[str, list[OHLCVBar]],
        strategy_engine: NuclearStrategyEngine,
        mtf_features: MultiTimeframeFeatures | None = None,
        regime: RegimeResult | None = None,
        cone: ItosCone | None = None,
        cone_merged: dict[str, Any] | None = None,
        symbol: str = "XAU_USD",
    ) -> BacktestResult:
        """
        Run the full shadow backtest.

        Parameters
        ----------
        ticks : list[TickSnapshot]
            Last 30 ticks from ticks_channel.
        bars_by_tf : dict
            All timeframe bar buffers from RedisStreamReader.
        strategy_engine : NuclearStrategyEngine
            Live strategy engine instance.
        mtf_features : MultiTimeframeFeatures, optional
            Pre-built features (avoids recomputing).
        regime : RegimeResult, optional
            Pre-classified regime.
        cone : ItosCone, optional
        cone_merged : dict, optional
        symbol : str

        Returns
        -------
        BacktestResult
        """
        all_trades: list[ShadowTrade] = []
        trade_id = 0

        # ── Phase 1: Tick-level simulation ────────────────────────────────────
        tick_trades, trade_id = self._simulate_ticks(
            ticks=ticks,
            bars_by_tf=bars_by_tf,
            strategy_engine=strategy_engine,
            cone=cone,
            cone_merged=cone_merged,
            symbol=symbol,
            trade_id_start=trade_id,
        )
        all_trades.extend(tick_trades)

        # ── Phase 2: Bar walk-forward simulation ──────────────────────────────
        bar_trades, trade_id = self._simulate_bars(
            bars_by_tf=bars_by_tf,
            strategy_engine=strategy_engine,
            cone=cone,
            cone_merged=cone_merged,
            symbol=symbol,
            trade_id_start=trade_id,
            n_bars=5,
        )
        all_trades.extend(bar_trades)

        # ── Aggregate metrics ─────────────────────────────────────────────────
        result = self._aggregate(
            trades=all_trades,
            symbol=symbol,
            ticks_tested=len(ticks),
            timeframes_tested=list(bars_by_tf.keys()),
        )

        logger.info(
            "ShadowBacktest %s: %d trades WR=%.1f%% Sharpe=%.2f MDD=%.2f%% conf=%.2f",
            symbol,
            result.total_trades,
            result.win_rate * 100,
            result.sharpe_ratio,
            result.max_drawdown_pct * 100,
            result.confidence_score,
        )
        return result

    # ── Tick simulation ───────────────────────────────────────────────────────

    def _simulate_ticks(
        self,
        ticks: list[TickSnapshot],
        bars_by_tf: dict[str, list[OHLCVBar]],
        strategy_engine: NuclearStrategyEngine,
        cone: ItosCone | None,
        cone_merged: dict[str, Any] | None,
        symbol: str,
        trade_id_start: int,
    ) -> tuple[list[ShadowTrade], int]:
        """Walk through ticks, generate signals, simulate fills."""
        trades: list[ShadowTrade] = []
        trade_id = trade_id_start
        n = len(ticks)

        if n < 2:
            return trades, trade_id

        # Use up to 30 ticks
        window = ticks[-30:]

        for i in range(1, len(window)):
            tick = window[i]

            # Build a minimal feature snapshot from available bars
            try:
                mtf = build_features_from_bars(bars_by_tf, symbol=symbol)
            except Exception as _exc:  # skip tick if feature build fails
                logger.debug("Feature build failed at tick %d for %s: %s", i, symbol, _exc)
                continue

            # Classify regime
            try:
                regime = self._clf.classify(mtf, cone_merged)
            except Exception as _exc:  # skip tick if regime classification fails
                logger.debug("Regime classification failed at tick %d for %s: %s", i, symbol, _exc)
                continue

            # Generate signal
            try:
                signal = strategy_engine.generate(
                    mtf=mtf,
                    regime=regime,
                    cone=cone,
                    cone_merged=cone_merged,
                    ticks=window[:i],
                )
            except Exception as _exc:  # skip tick if signal generation fails
                logger.debug("Signal generation failed at tick %d for %s: %s", i, symbol, _exc)
                continue

            if signal is None or signal.direction == FLAT:
                continue

            # Simulate fill at current tick mid
            fill_price = self._fill_price(tick.mid, signal.direction)

            # Simulate exit at next tick (or timeout)
            if i + 1 < len(window):
                next_tick = window[i + 1]
                exit_price, exit_reason = self._simulate_exit(
                    fill_price=fill_price,
                    direction=signal.direction,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit_1,
                    next_price=next_tick.mid,
                )
                exit_time = next_tick.timestamp
            else:
                exit_price = tick.mid
                exit_reason = "timeout"
                exit_time = tick.timestamp

            pnl_pips, pnl_pct = self._compute_pnl(fill_price, exit_price, signal.direction)

            trades.append(
                ShadowTrade(
                    trade_id=trade_id,
                    direction=signal.direction,
                    strategy=signal.strategy,
                    entry_price=fill_price,
                    exit_price=exit_price,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit_1,
                    entry_time=tick.timestamp,
                    exit_time=exit_time,
                    exit_reason=exit_reason,
                    pnl_pips=pnl_pips,
                    pnl_pct=pnl_pct,
                    confidence=signal.confidence,
                    regime=signal.regime,
                    timeframe=signal.timeframe,
                    cone_aligned=signal.cone_aligned,
                )
            )
            trade_id += 1

        return trades, trade_id

    # ── Bar walk-forward simulation ───────────────────────────────────────────

    def _simulate_bars(
        self,
        bars_by_tf: dict[str, list[OHLCVBar]],
        strategy_engine: NuclearStrategyEngine,
        cone: ItosCone | None,
        cone_merged: dict[str, Any] | None,
        symbol: str,
        trade_id_start: int,
        n_bars: int = 5,
    ) -> tuple[list[ShadowTrade], int]:
        """Walk-forward bar simulation: generate signal on bar[i], exit on bar[i+1]."""
        trades: list[ShadowTrade] = []
        trade_id = trade_id_start

        for tf, bars in bars_by_tf.items():
            if len(bars) < _MIN_BARS_PER_TF + 1:
                continue

            # Walk through last n_bars bars
            walk_bars = bars[-(n_bars + 1) :]

            for i in range(len(walk_bars) - 1):
                history = bars[: -(n_bars - i)] if (n_bars - i) > 0 else bars
                if len(history) < 2:
                    continue

                # Build features from history up to bar i
                try:
                    mtf = build_features_from_bars(
                        {tf: history},
                        symbol=symbol,
                    )
                except Exception as _exc:  # skip bar if feature build fails
                    logger.debug("Feature build failed at bar %d/%s for %s: %s", i, tf, symbol, _exc)
                    continue

                # Compute cone from this TF's history
                try:
                    closes = np.array([b.close for b in history if b.close > 0])
                    tf_cone = (
                        self._cone_engine.compute(closes, symbol=symbol, timeframe=tf) if len(closes) >= 10 else cone
                    )
                    tf_cone_merged = cone_merged
                except Exception as _exc:  # non-fatal: fall back to parent cone
                    logger.debug("Cone computation failed at bar %d/%s for %s: %s", i, tf, symbol, _exc)
                    tf_cone = cone
                    tf_cone_merged = cone_merged

                # Classify regime
                try:
                    regime = self._clf.classify(mtf, tf_cone_merged)
                except Exception as _exc:  # skip bar if regime classification fails
                    logger.debug("Regime classification failed at bar %d/%s for %s: %s", i, tf, symbol, _exc)
                    continue

                # Generate signal on bar close
                try:
                    signal = strategy_engine.generate(
                        mtf=mtf,
                        regime=regime,
                        cone=tf_cone,
                        cone_merged=tf_cone_merged,
                    )
                except Exception as _exc:  # skip bar if signal generation fails
                    logger.debug("Signal generation failed at bar %d/%s for %s: %s", i, tf, symbol, _exc)
                    continue

                if signal is None or signal.direction == FLAT:
                    continue

                # Entry: next bar open (simulate market order)
                next_bar = walk_bars[i + 1]
                fill_price = self._fill_price(next_bar.open, signal.direction)

                # Exit: check if SL/TP hit within next bar's range
                exit_price, exit_reason = self._simulate_exit_on_bar(
                    fill_price=fill_price,
                    direction=signal.direction,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit_1,
                    bar_high=next_bar.high,
                    bar_low=next_bar.low,
                    bar_close=next_bar.close,
                )

                pnl_pips, pnl_pct = self._compute_pnl(fill_price, exit_price, signal.direction)

                trades.append(
                    ShadowTrade(
                        trade_id=trade_id,
                        direction=signal.direction,
                        strategy=signal.strategy,
                        entry_price=fill_price,
                        exit_price=exit_price,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit_1,
                        entry_time=next_bar.open_time,
                        exit_time=next_bar.close_time or next_bar.open_time,
                        exit_reason=exit_reason,
                        pnl_pips=pnl_pips,
                        pnl_pct=pnl_pct,
                        confidence=signal.confidence,
                        regime=signal.regime,
                        timeframe=tf,
                        cone_aligned=signal.cone_aligned,
                    )
                )
                trade_id += 1

        return trades, trade_id

    # ── Fill and exit simulation ──────────────────────────────────────────────

    def _fill_price(self, mid: float, direction: str) -> float:
        """Simulate realistic fill with spread + impact + noise."""
        noise = float(self._rng.normal(0, self._noise))
        slippage = self._half_spread + self._impact + abs(noise)
        if direction == LONG:
            return mid * (1 + slippage)
        return mid * (1 - slippage)

    def _simulate_exit(
        self,
        fill_price: float,
        direction: str,
        stop_loss: float,
        take_profit: float,
        next_price: float,
    ) -> tuple[float, str]:
        """Simulate exit at next tick: check SL/TP, else close at market."""
        if direction == LONG:
            if next_price <= stop_loss:
                return stop_loss, "sl"
            if next_price >= take_profit:
                return take_profit, "tp1"
        else:
            if next_price >= stop_loss:
                return stop_loss, "sl"
            if next_price <= take_profit:
                return take_profit, "tp1"
        return next_price, "timeout"

    def _simulate_exit_on_bar(
        self,
        fill_price: float,
        direction: str,
        stop_loss: float,
        take_profit: float,
        bar_high: float,
        bar_low: float,
        bar_close: float,
    ) -> tuple[float, str]:
        """
        Simulate exit within a bar's range.

        Assumes worst-case: SL is checked before TP (conservative).
        """
        if direction == LONG:
            if bar_low <= stop_loss:
                return stop_loss, "sl"
            if bar_high >= take_profit:
                return take_profit, "tp1"
        else:
            if bar_high >= stop_loss:
                return stop_loss, "sl"
            if bar_low <= take_profit:
                return take_profit, "tp1"
        return bar_close, "timeout"

    @staticmethod
    def _compute_pnl(
        entry: float,
        exit_price: float,
        direction: str,
    ) -> tuple[float, float]:
        """Return (pnl_pips, pnl_pct)."""
        pnl_pips = exit_price - entry if direction == LONG else entry - exit_price
        pnl_pct = pnl_pips / (entry + 1e-9)
        return pnl_pips, pnl_pct

    # ── Aggregation ───────────────────────────────────────────────────────────

    def _aggregate(
        self,
        trades: list[ShadowTrade],
        symbol: str,
        ticks_tested: int,
        timeframes_tested: list[str],
    ) -> BacktestResult:
        """Compute aggregate performance metrics from trade list."""
        if not trades:
            return BacktestResult(
                symbol=symbol,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                profit_factor=0.0,
                sharpe_ratio=0.0,
                max_drawdown_pct=0.0,
                total_pnl_pct=0.0,
                avg_pnl_pct=0.0,
                avg_win_pct=0.0,
                avg_loss_pct=0.0,
                best_trade_pct=0.0,
                worst_trade_pct=0.0,
                avg_rr=0.0,
                cone_aligned_win_rate=0.0,
                trades=[],
                equity_curve=[1.0],
                timeframes_tested=timeframes_tested,
                ticks_tested=ticks_tested,
            )

        pnls = np.array([t.pnl_pct for t in trades])
        winners = [t for t in trades if t.is_winner]
        losers = [t for t in trades if not t.is_winner]

        win_rate = len(winners) / len(trades)
        gross_profit = sum(t.pnl_pct for t in winners)
        gross_loss = abs(sum(t.pnl_pct for t in losers))
        profit_factor = gross_profit / (gross_loss + 1e-9)

        # Sharpe (annualised, assuming daily bars)
        sharpe = float(np.mean(pnls) / (np.std(pnls, ddof=1) + 1e-9)) * math.sqrt(252) if len(pnls) > 1 else 0.0

        # Equity curve and max drawdown
        equity = np.cumprod(1 + pnls)
        peak = np.maximum.accumulate(equity)
        drawdowns = (equity - peak) / (peak + 1e-9)
        max_dd = float(np.min(drawdowns))

        # Cone-aligned win rate
        aligned = [t for t in trades if t.cone_aligned]
        cone_wr = sum(1 for t in aligned if t.is_winner) / len(aligned) if aligned else 0.0

        # Average realised RR
        avg_rr = (
            float(np.mean([abs(t.pnl_pct) / abs(t.entry_price - t.stop_loss + 1e-9) * t.entry_price for t in trades]))
            if trades
            else 0.0
        )

        # Regime and strategy breakdowns
        regime_breakdown: dict[str, int] = {}
        strategy_breakdown: dict[str, int] = {}
        for t in trades:
            regime_breakdown[t.regime] = regime_breakdown.get(t.regime, 0) + 1
            strategy_breakdown[t.strategy] = strategy_breakdown.get(t.strategy, 0) + 1

        return BacktestResult(
            symbol=symbol,
            total_trades=len(trades),
            winning_trades=len(winners),
            losing_trades=len(losers),
            win_rate=win_rate,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe,
            max_drawdown_pct=abs(max_dd),
            total_pnl_pct=float(np.sum(pnls)),
            avg_pnl_pct=float(np.mean(pnls)),
            avg_win_pct=float(np.mean([t.pnl_pct for t in winners])) if winners else 0.0,
            avg_loss_pct=float(np.mean([t.pnl_pct for t in losers])) if losers else 0.0,
            best_trade_pct=float(np.max(pnls)),
            worst_trade_pct=float(np.min(pnls)),
            avg_rr=avg_rr,
            cone_aligned_win_rate=cone_wr,
            trades=trades,
            equity_curve=equity.tolist(),
            timeframes_tested=timeframes_tested,
            ticks_tested=ticks_tested,
            regime_breakdown=regime_breakdown,
            strategy_breakdown=strategy_breakdown,
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_backtest_instance: ShadowBacktestEngine | None = None


def get_shadow_backtest(rng_seed: int | None = 42) -> ShadowBacktestEngine:
    """Return the process-wide ShadowBacktestEngine singleton."""
    global _backtest_instance
    if _backtest_instance is None:
        _backtest_instance = ShadowBacktestEngine(rng_seed=rng_seed)
    return _backtest_instance
