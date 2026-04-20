# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
backtesting/backtest_engine.py
==============================
Vectorised signal-based backtester.

Signals: +1 = long, -1 = short, 0 = flat.
Positions are sized as a fixed fraction of equity (default 10%).

Cost model (unified — all three components wired to the same source):
  1. Round-trip spread + commission via TransactionCostModel (bps of notional).
     Default: 6.5 bps total for XAU/USD (1.5 bps half-spread x2 + 3.5 bps
     commission).  The old flat 35 bps commission_pct was ~5x too high.
  2. Overnight financing via OvernightSwapModel (USD per lot per night).
     Default: -$4.10/night per 100oz lot for XAU/USD long.
     The old 0.4% p.a. annualised-notional model undercharged by ~47%.
  3. Wednesday triple-swap applied automatically when bar timestamps are
     available (3x nightly rate to cover the Sat/Sun settlement gap).

Sharpe (corrected):
  Computed at trade level: mean(net_pnl) / std(net_pnl) * sqrt(252 / avg_hold_days).
  Bar-level Sharpe is NOT reported — flat no-trade bars suppress the return
  std and inflate the ratio by 3-5x on daily-bar strategies.

Monte Carlo (corrected):
  Uses block bootstrap (block_size = avg hold period in bars) to preserve
  the serial autocorrelation structure of trade returns.  The old IID
  bootstrap destroyed autocorrelation and underestimated tail risk.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backtesting.transaction_costs import OvernightSwapModel, TransactionCostModel, get_swap_model, get_tc_model


@dataclass
class BacktestResult:
    total_return: float
    sharpe_ratio: float       # trade-level (corrected)
    max_drawdown: float
    win_rate: float
    total_trades: int
    equity_curve: list[float] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    total_commission: float = 0.0
    total_overnight_cost: float = 0.0
    sharpe_se: float = 0.0    # 1/sqrt(2*(N-1)) — credibility indicator
    ticker: str = "XAUUSD"


class BacktestEngine:
    """
    Vectorised backtester with unified, institutionally-calibrated cost model.

    Parameters
    ----------
    initial_balance   : Starting equity in USD.
    position_size_pct : Fraction of equity allocated per trade (default 10%).
    ticker            : Instrument ticker used for cost lookups (default XAUUSD).
    tc_model          : TransactionCostModel instance.  None = use module singleton.
    swap_model        : OvernightSwapModel instance.  None = use module singleton.
    bars_per_day      : Bar frequency (24=H1, 4=H4, 1=D1).  Used for Sharpe
                        annualisation and overnight charge frequency.
    """

    def __init__(
        self,
        initial_balance: float = 100_000.0,
        position_size_pct: float = 0.10,
        ticker: str = "XAUUSD",
        tc_model: TransactionCostModel | None = None,
        swap_model: OvernightSwapModel | None = None,
        bars_per_day: int = 24,
        # Legacy parameter kept for backward compatibility — ignored when
        # tc_model is provided.  If only commission_pct is supplied (no
        # tc_model), a TransactionCostModel is constructed from it.
        commission_pct: float | None = None,
        # Legacy overnight rate — ignored when swap_model is provided.
        overnight_rate_annual: float | None = None,
    ):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.position_size_pct = position_size_pct
        self.ticker = ticker
        self.bars_per_day = bars_per_day

        # Cost model: prefer explicit tc_model; fall back to legacy commission_pct
        if tc_model is not None:
            self._tc = tc_model
        elif commission_pct is not None:
            # Legacy path: convert flat commission_pct to a TransactionCostModel
            # by expressing it as extra spread bps on top of the table value.
            table_cost = get_tc_model().round_trip_cost_frac(ticker)
            extra_bps = max(0.0, (commission_pct - table_cost) * 10_000)
            self._tc = TransactionCostModel(extra_spread_bps=extra_bps)
        else:
            self._tc = get_tc_model()

        # Swap model: prefer explicit swap_model; fall back to legacy annual rate
        if swap_model is not None:
            self._swap = swap_model
        elif overnight_rate_annual is not None:
            # Legacy path: wrap the annual rate in a thin adapter so the rest
            # of the engine uses a uniform interface.
            self._swap = _LegacyAnnualRateSwap(overnight_rate_annual, bars_per_day)
        else:
            self._swap = get_swap_model()

        self.trades: list[dict] = []
        self.equity_curve: list[float] = [initial_balance]

    # ------------------------------------------------------------------
    def run_backtest(
        self,
        data: pd.DataFrame,
        signals,  # pd.Series or callable(data) -> pd.Series
    ) -> BacktestResult:
        """
        Run a vectorised backtest.

        Parameters
        ----------
        data    : OHLCV DataFrame with columns open/high/low/close/volume.
                  Index should be a DatetimeIndex for Wednesday triple-swap.
        signals : pd.Series of {-1, 0, 1} aligned to data.index,
                  OR a callable that receives data and returns such a Series.
        """
        if callable(signals):
            signals = signals(data)

        signals = pd.Series(signals, index=data.index).fillna(0)

        # Detect whether the index carries weekday information
        has_datetime_index = isinstance(data.index, pd.DatetimeIndex)

        # Reset state
        self.balance = self.initial_balance
        self.trades = []
        equity = [self.initial_balance]
        total_commission = 0.0
        total_overnight = 0.0

        position = 0.0        # current position size in base units (oz for gold)
        entry_price = 0.0
        entry_signal = 0
        entry_bar = 0         # bar index at entry — used for hold-period tracking

        for i in range(1, len(data)):
            prev_sig = signals.iloc[i - 1]
            price = float(data["close"].iloc[i])

            # ── Close existing position on signal flip or exit ────────────
            if position != 0 and (prev_sig == 0 or prev_sig != entry_signal):
                raw_pnl = position * (price - entry_price)
                # Round-trip cost: fraction of exit notional
                rt_cost_frac = self._tc.round_trip_cost_frac(self.ticker)
                commission = abs(position) * price * rt_cost_frac
                total_commission += commission
                net_pnl = raw_pnl - commission
                self.balance += net_pnl
                hold_bars = i - entry_bar
                self.trades.append(
                    {
                        "entry_price": entry_price,
                        "exit_price": price,
                        "size": position,
                        "pnl": net_pnl,
                        "win": net_pnl > 0,
                        "hold_bars": hold_bars,
                    }
                )
                position = 0.0

            # ── Open new position ─────────────────────────────────────────
            if prev_sig != 0 and position == 0.0:
                size = (self.balance * self.position_size_pct) / price
                position = size if prev_sig == 1 else -size
                entry_price = price
                entry_signal = prev_sig
                entry_bar = i

            # ── Overnight financing — charged every bar on open positions ─
            if position != 0.0:
                side = "long" if position > 0 else "short"
                lots = abs(position) / 100.0  # 100 oz per standard lot for gold

                # Extract weekday for Wednesday triple-swap when available
                weekday: int | None = None
                if has_datetime_index:
                    try:
                        weekday = int(data.index[i].weekday())
                    except Exception:  # nosec B110 — non-fatal; fall back to no triple-swap
                        pass

                # cost_usd_per_night gives the full nightly charge.
                # We distribute it evenly across bars_per_day bars so the
                # total per calendar day equals exactly one nightly charge.
                cost_per_bar = abs(
                    self._swap.cost_usd_per_night(
                        self.ticker, lots=lots, side=side, weekday=weekday
                    )
                ) / max(self.bars_per_day, 1)

                self.balance -= cost_per_bar
                total_overnight += cost_per_bar

            equity.append(self.balance)

        # ── Force-close at end ────────────────────────────────────────────
        if position != 0.0:
            price = float(data["close"].iloc[-1])
            raw_pnl = position * (price - entry_price)
            rt_cost_frac = self._tc.round_trip_cost_frac(self.ticker)
            commission = abs(position) * price * rt_cost_frac
            total_commission += commission
            net_pnl = raw_pnl - commission
            self.balance += net_pnl
            hold_bars = len(data) - 1 - entry_bar
            self.trades.append(
                {
                    "entry_price": entry_price,
                    "exit_price": price,
                    "size": position,
                    "pnl": net_pnl,
                    "win": net_pnl > 0,
                    "hold_bars": hold_bars,
                }
            )
            equity[-1] = self.balance

        self.equity_curve = equity

        # ── Metrics ───────────────────────────────────────────────────────
        eq = np.array(equity, dtype=float)
        total_return = (eq[-1] - eq[0]) / eq[0]

        roll_max = np.maximum.accumulate(eq)
        drawdowns = (eq - roll_max) / np.where(roll_max != 0, roll_max, 1.0)
        max_drawdown = float(drawdowns.min())

        n = len(self.trades)
        win_rate = sum(1 for t in self.trades if t["win"]) / n if n > 0 else 0.0

        # Trade-level Sharpe (corrected — not bar-level)
        sharpe, sharpe_se = _trade_level_sharpe(self.trades, self.bars_per_day)

        return BacktestResult(
            total_return=float(total_return),
            sharpe_ratio=sharpe,
            max_drawdown=float(max_drawdown),
            win_rate=float(win_rate),
            total_trades=n,
            equity_curve=equity,
            trades=self.trades,
            total_commission=float(total_commission),
            total_overnight_cost=float(total_overnight),
            sharpe_se=sharpe_se,
            ticker=self.ticker,
        )

    # ------------------------------------------------------------------
    def monte_carlo_analysis(
        self,
        n_simulations: int = 5000,
        block_size: int | None = None,
    ) -> dict:
        """
        Block-bootstrap Monte Carlo over trade PnLs.

        Block bootstrap preserves the serial autocorrelation structure of
        trade returns (trending regimes produce runs of wins; mean-reverting
        regimes produce runs of losses).  IID resampling destroys this
        structure and underestimates tail risk.

        Parameters
        ----------
        n_simulations : Number of bootstrap paths (default 5 000).
        block_size    : Contiguous block length in trades.  None = use the
                        average hold period in bars (aligns block size with
                        the natural autocorrelation horizon of the strategy).

        Returns
        -------
        Dict with mean_return, std_return, percentile_5, percentile_95,
        ruin_probability, n_simulations, method.
        """
        if not self.trades:
            return {}

        pnls = np.array([t["pnl"] for t in self.trades])
        n_trades = len(pnls)

        # Default block size = average hold period in bars (minimum 2)
        if block_size is None:
            hold_bars = [t.get("hold_bars", 5) for t in self.trades]
            block_size = max(2, int(round(float(np.mean(hold_bars)))))

        rng = np.random.default_rng(42)
        sim_returns: list[float] = []
        ruin_count = 0
        ruin_threshold = self.initial_balance * 0.5

        for _ in range(n_simulations):
            sampled = _block_resample(pnls, n_trades, block_size, rng)
            equity = self.initial_balance
            ruined = False
            for pnl in sampled:
                equity += pnl
                if equity <= ruin_threshold:
                    ruined = True
                    break
            if ruined:
                ruin_count += 1
                sim_returns.append(-0.5)
            else:
                sim_returns.append((equity - self.initial_balance) / self.initial_balance)

        arr = np.array(sim_returns)
        return {
            "mean_return": float(np.mean(arr)),
            "std_return": float(np.std(arr)),
            "percentile_5": float(np.percentile(arr, 5)),
            "percentile_95": float(np.percentile(arr, 95)),
            "ruin_probability": ruin_count / n_simulations,
            "n_simulations": n_simulations,
            "block_size": block_size,
            "method": "block_bootstrap",
        }


# ── Helpers ───────────────────────────────────────────────────────────────────


def _trade_level_sharpe(
    trades: list[dict],
    bars_per_day: int,
) -> tuple[float, float]:
    """
    Compute trade-level annualised Sharpe ratio and its standard error.

    Formula: mean(net_pnl) / std(net_pnl) * sqrt(252 / avg_hold_days)

    Returns (sharpe, sharpe_se).  sharpe_se = 1/sqrt(2*(N-1)) for iid returns.
    """
    if len(trades) < 2:
        return 0.0, 0.0
    pnls = np.array([t["pnl"] for t in trades], dtype=float)
    std = float(np.std(pnls, ddof=1))
    if std == 0:
        return 0.0, 0.0
    hold_bars_arr = np.array([t.get("hold_bars", bars_per_day) for t in trades], dtype=float)
    avg_hold_days = float(np.mean(hold_bars_arr)) / max(bars_per_day, 1)
    ann_factor = math.sqrt(252.0 / max(avg_hold_days, 1.0 / 252))
    sharpe = float(np.mean(pnls) / std * ann_factor)
    sharpe_se = 1.0 / math.sqrt(max(2.0 * (len(pnls) - 1), 1e-9))
    return sharpe, sharpe_se


def _block_resample(
    pnls: np.ndarray,
    n_trades: int,
    block_size: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Resample contiguous blocks of trades to preserve autocorrelation."""
    n = len(pnls)
    blocks: list[np.ndarray] = []
    total = 0
    while total < n_trades:
        start = int(rng.integers(0, n))
        end = min(start + block_size, n)
        blocks.append(pnls[start:end])
        total += end - start
    return np.concatenate(blocks)[:n_trades]


class _LegacyAnnualRateSwap:
    """
    Thin adapter that wraps a legacy annualised-rate float so the engine
    can call the same OvernightSwapModel interface.

    Used only when the caller passes overnight_rate_annual= explicitly.
    """

    def __init__(self, annual_rate: float, bars_per_day: int) -> None:
        self._rate_per_bar = annual_rate / 365.0 / max(bars_per_day, 1)

    def cost_usd_per_night(
        self,
        ticker: str,
        lots: float,
        side: str,
        weekday: int | None = None,
    ) -> float:
        # Convert lots back to notional using a rough $200 000/lot assumption
        # (100 oz × $2 000/oz).  This is only used when the caller explicitly
        # passes overnight_rate_annual= — the preferred path uses OvernightSwapModel.
        notional_per_lot = 200_000.0
        notional = lots * notional_per_lot
        return -(notional * self._rate_per_bar)


# Alias kept for backward compatibility
Backtest = BacktestEngine
