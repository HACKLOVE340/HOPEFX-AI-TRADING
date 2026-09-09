# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
backtesting/engine_config.py
============================
Config-driven backtesting engine: BacktestConfig, SimulatedBroker,
BacktestEngine (config-based), BacktestResult.

This is the canonical location for the rich config-based backtest API.
The event-driven engine (backtesting/engine.py) handles tick-level
simulation; this module handles OHLCV bar-level simulation with:
  - Kelly-based position sizing
  - Variable slippage (gold pip = $0.10)
  - Overnight financing charges
  - Monte Carlo simulation
  - Regime breakdown
  - Trade-level Sharpe (corrected — not bar-level)

Imports
-------
  from backtesting.engine_config import BacktestConfig, BacktestEngine, SimulatedBroker, BacktestResult

The legacy shim at backtest/engine.py re-exports from here.
"""

import contextlib
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from scipy import stats as _scipy_stats

    SCIPY_AVAILABLE = True
except ImportError:
    _scipy_stats = None  # type: ignore[assignment]
    SCIPY_AVAILABLE = False

from backtesting.transaction_costs import OvernightSwapModel, TransactionCostModel, get_swap_model, get_tc_model

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """Backtest configuration"""

    start_date: datetime
    end_date: datetime
    symbols: list[str]
    initial_capital: float = 100000.0
    # Primary instrument ticker — used for cost model lookups.
    # Accepts any alias: "XAUUSD", "GC=F", "XAU/USD", "EURUSD", etc.
    ticker: str = "XAUUSD"
    # commission_per_trade is kept for backward compatibility but is IGNORED
    # when use_unified_costs=True (the default).  The unified TransactionCostModel
    # computes the correct bps-of-notional cost per instrument automatically.
    commission_per_trade: float = 7.0
    # use_unified_costs: when True (default), TransactionCostModel and
    # OvernightSwapModel are used for all cost calculations.  Set False only
    # to reproduce legacy results for comparison.
    use_unified_costs: bool = True
    slippage_model: str = "almgren_chriss"  # almgren_chriss, variable, fixed, none
    # Gold spread: ~$0.30 typical, $0.50 conservative.  1 pip for gold = $0.10.
    # 3 pips = $0.30 spread — realistic for XAU/USD.
    slippage_pips: float = 3.0
    allow_short: bool = True
    max_positions: int = 10
    # overnight_rate_annual is kept for backward compatibility but is IGNORED
    # when use_unified_costs=True.  The OvernightSwapModel uses real USD/lot/night
    # rates (-$4.10/night per 100oz lot for XAU/USD long) which is ~47% higher
    # than the old 0.4% p.a. annualised-notional approximation.
    overnight_rate_annual: float = 0.004
    bars_per_day: float = 24.0  # 24 for H1, 6 for H4, 1 for D
    # Kelly-based position sizing.  0 = use fixed lot from signal.
    # 0.25 = quarter-Kelly (recommended for live trading).
    kelly_fraction: float = 0.25
    # Risk per trade as fraction of equity (used when kelly_fraction > 0).
    risk_per_trade: float = 0.01  # 1% of equity per trade
    # Minimum R:R ratio to accept a trade (0 = no filter).
    min_rr_ratio: float = 1.5


@dataclass
class BacktestResult:
    """Backtest results"""

    total_return: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown: float
    # sharpe_ratio: trade-level Sharpe (mean/std of net_pnl * sqrt(252/avg_hold_days)).
    # This is the credible number.  Bar-level Sharpe is inflated by flat no-trade days.
    sharpe_ratio: float
    equity_curve: list[dict]
    trades: list[dict]
    metrics: dict[str, float]
    # Extended risk-adjusted metrics (Area 1)
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    omega_ratio: float = 0.0
    tail_ratio: float = 0.0
    skewness: float = 0.0
    kurtosis: float = 0.0
    avg_mae: float = 0.0
    avg_mfe: float = 0.0
    # Statistical significance (Area 1)
    t_statistic: float = 0.0
    p_value: float = 1.0
    is_significant: bool = False
    sample_size: int = 0
    # Sharpe standard error: 1/sqrt(2*(N-1)) — valid for iid trade returns.
    sharpe_se: float = 0.0
    # Monte Carlo (Area 1)
    mc_median_final: float = 0.0
    mc_p5_final: float = 0.0
    mc_p95_final: float = 0.0
    mc_ruin_probability: float = 0.0
    # Regime breakdown (Area 1)
    regime_breakdown: dict[str, Any] = field(default_factory=dict)


class HistoricalDataLoader:
    """Load historical data for backtesting"""

    def __init__(self, data_source: str = "database"):
        self.data_source = data_source
        self._cache: dict[str, pd.DataFrame] = {}

    async def load_data(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame | None:
        """
        Load historical OHLCV data and validate it before returning.

        Validation enforces:
        - No NaN/Inf in OHLC columns
        - Strictly monotonic timestamps (look-ahead bias prevention)
        - Price sanity (high >= low, positive prices)
        - No future-dated bars relative to the backtest end date
        """
        cache_key = f"{symbol}_{timeframe}_{start}_{end}"

        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            # Try database first
            if self.data_source == "database":
                from database.connection import get_db_manager

                db = get_db_manager()

                if db:
                    # Query database
                    query = """
                        SELECT timestamp, open, high, low, close, volume
                        FROM market_data
                        WHERE symbol = :symbol
                        AND timeframe = :timeframe
                        AND timestamp BETWEEN :start AND :end
                        ORDER BY timestamp
                    """

                    with db._engine.connect() as conn:
                        df = pd.read_sql(
                            query,
                            conn,
                            params={
                                "symbol": symbol,
                                "timeframe": timeframe,
                                "start": start,
                                "end": end,
                            },
                        )

                        df = self._validate_and_clean(df, symbol)
                        self._cache[cache_key] = df
                        return df

            # No data found in any source — raise so the caller knows
            # the backtest cannot proceed with real data.
            raise FileNotFoundError(
                f"No historical data found for {symbol} "
                f"({start.date()} – {end.date()}) in CSV files or database. "
                "Download real OHLCV data before running a backtest."
            )

        except FileNotFoundError:
            raise  # propagate the explicit error above
        except Exception as e:
            logger.error("Failed to load data for %s: %s", symbol, e)

            raise

    def _validate_and_clean(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Run the data validation layer on a loaded OHLCV DataFrame.

        Uses data_layer.validation.validate_ohlcv in non-strict mode so that
        recoverable issues (NaN rows, duplicate timestamps) are cleaned rather
        than raising.  Unrecoverable issues (e.g. all-NaN price columns) still
        raise DataValidationError.
        """
        if df is None or df.empty:
            return df
        try:
            from data_layer.validation import validate_ohlcv

            df = validate_ohlcv(
                df,
                symbol=symbol,
                strict=False,  # clean recoverable issues, don't raise
                drop_bad_rows=True,  # remove rows with invalid prices
            )
            logger.debug(
                "HistoricalDataLoader: validated %d bars for %s",
                len(df),
                symbol,
            )
        except Exception as val_exc:
            # Validation failure is non-fatal for loading — log and continue.
            # The backtest engine will surface data quality issues via results.
            logger.warning(
                "HistoricalDataLoader: validation warning for %s: %s",
                symbol,
                val_exc,
            )
        return df


class SimulatedBroker:
    """Broker simulation for backtesting"""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.cash = config.initial_capital
        self.positions: dict[str, dict] = {}
        self.trades: list[dict] = []
        self.equity_curve: list[dict] = []
        self.current_time: datetime | None = None
        self.total_overnight_cost: float = 0.0

        use_unified = getattr(config, "use_unified_costs", True)
        bars_per_day = float(getattr(config, "bars_per_day", 24.0))
        ticker = getattr(config, "ticker", "XAUUSD")

        if use_unified:
            # Unified cost models — broker-independent, calibrated to real rates
            self._tc: TransactionCostModel = get_tc_model()
            self._swap: OvernightSwapModel = get_swap_model()
            self._use_unified = True
        else:
            # Legacy path: annualised-rate model (kept for comparison only)
            annual_rate = getattr(config, "overnight_rate_annual", 0.004)
            self._overnight_rate_per_bar = annual_rate / 365.0 / bars_per_day
            self._use_unified = False

        self._bars_per_day = bars_per_day
        self._ticker = ticker

    def update_time(self, timestamp: datetime):
        """Update current simulation time and apply overnight financing."""
        self.current_time = timestamp

        # Overnight financing: charged every bar on open positions.
        if self.positions:
            weekday: int | None = None
            with contextlib.suppress(Exception):  # nosec B110 — non-fatal; fall back to no triple-swap
                weekday = int(timestamp.weekday())

            for symbol, pos in self.positions.items():
                price = pos.get("current_price", pos.get("avg_price", 0.0))
                qty = pos.get("quantity", 0.0)
                if qty == 0 or price == 0:
                    continue
                side = "long" if qty > 0 else "short"
                ticker = symbol if symbol else self._ticker

                if self._use_unified:
                    # OvernightSwapModel: USD per standard lot per night.
                    # Distribute evenly across bars_per_day bars so the total
                    # per calendar day equals exactly one nightly charge.
                    lots = abs(qty) / 100.0  # 100 oz per standard lot for gold
                    cost_per_bar = abs(
                        self._swap.cost_usd_per_night(ticker, lots=lots, side=side, weekday=weekday)
                    ) / max(self._bars_per_day, 1.0)
                else:
                    # Legacy: annualised rate on notional
                    notional = abs(qty * price)
                    cost_per_bar = notional * self._overnight_rate_per_bar

                self.cash -= cost_per_bar
                self.total_overnight_cost += cost_per_bar

        # Record equity
        equity = self.get_equity()
        self.equity_curve.append(
            {
                "timestamp": timestamp.isoformat(),
                "equity": equity,
                "cash": self.cash,
                "positions_value": equity - self.cash,
            }
        )

    def get_equity(self) -> float:
        """Calculate total equity"""
        positions_value = sum(pos["quantity"] * pos["current_price"] for pos in self.positions.values())
        return self.cash + positions_value

    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        current_price: float,
        bar_high: float = 0.0,
        bar_low: float = 0.0,
    ) -> dict:
        """Simulate market order execution"""
        # Apply slippage (variable model uses bar range)
        slippage = self._calculate_slippage(current_price, bar_high, bar_low)

        fill_price = current_price * (1 + slippage) if side == "buy" else current_price * (1 - slippage)

        # Calculate cost — unified TransactionCostModel (bps of notional)
        # or legacy flat commission depending on config.use_unified_costs.
        cost = quantity * fill_price
        if self._use_unified:
            # Half the round-trip cost on entry, half on exit (symmetric).
            rt_frac = self._tc.round_trip_cost_frac(self._ticker)
            commission = cost * rt_frac / 2.0
        else:
            commission = self.config.commission_per_trade

        # Check funds
        if side == "buy" and cost + commission > self.cash:
            return {"success": False, "error": "Insufficient funds"}

        # Execute
        if side == "buy":
            self.cash -= cost + commission

            if symbol in self.positions:
                # Add to existing position
                pos = self.positions[symbol]
                total_qty = pos["quantity"] + quantity
                avg_price = (pos["avg_price"] * pos["quantity"] + fill_price * quantity) / total_qty
                pos["quantity"] = total_qty
                pos["avg_price"] = avg_price
            else:
                # New position
                self.positions[symbol] = {
                    "quantity": quantity,
                    "avg_price": fill_price,
                    "current_price": current_price,
                    "side": "long",
                }
        else:
            # Sell
            self.cash += cost - commission

            if symbol in self.positions:
                pos = self.positions[symbol]
                if pos["quantity"] <= quantity:
                    # Close position
                    realized_pnl = (fill_price - pos["avg_price"]) * pos["quantity"]
                    if pos["side"] == "short":
                        realized_pnl = -realized_pnl

                    self._record_trade(
                        symbol,
                        "close",
                        pos["quantity"],
                        pos["avg_price"],
                        fill_price,
                        realized_pnl,
                        commission,
                    )
                    del self.positions[symbol]
                else:
                    # Partial close
                    pos["quantity"] -= quantity
            else:
                # Short sell
                self.positions[symbol] = {
                    "quantity": quantity,
                    "avg_price": fill_price,
                    "current_price": current_price,
                    "side": "short",
                }

        return {
            "success": True,
            "fill_price": fill_price,
            "quantity": quantity,
            "commission": commission,
        }

    def _calculate_slippage(
        self,
        price: float,
        bar_high: float = 0.0,
        bar_low: float = 0.0,
        bar_volume: float = 0.0,
        adv: float = 0.0,
        quantity: float = 1.0,
        side: str = "BUY",
    ) -> float:
        """
        Calculate execution slippage as a fraction of price.

        slippage_model options:
          "almgren_chriss" — Almgren-Chriss (2001) model: temporary + permanent
                             impact + spread + queue position. Most realistic.
          "variable"       — Bar-range scaled spread model (legacy).
          "fixed"          — Fixed pip-based spread (legacy).
          "none"           — Zero slippage (optimistic, not recommended).

        Gold (XAU/USD) pip convention: 1 pip = $0.10 (i.e. 0.1 USD per oz).
        A 3-pip spread at $2000/oz = $0.30 = 0.015% — realistic for OANDA practice.
        """
        if self.config.slippage_model == "none":
            return 0.0

        if self.config.slippage_model == "almgren_chriss":
            # Almgren-Chriss: realistic impact including partial fills and queue position.
            try:
                from execution.market_impact import AlmgrenChrissModel

                model = AlmgrenChrissModel()
                # Estimate daily volatility from bar range if not provided
                if price > 0 and bar_high > bar_low:
                    bar_range_pct = (bar_high - bar_low) / price
                    # Approximate daily vol: bar range / sqrt(bars_per_day)
                    bars_per_day = getattr(self.config, "bars_per_day", 24.0)
                    bar_range_pct = float(np.nan_to_num(bar_range_pct, nan=0.0))
                    vol_daily = bar_range_pct / np.sqrt(max(bars_per_day, 1e-9))
                else:
                    vol_daily = 0.012  # 1.2% default (gold ~1%)

                # Spread: use config pips converted to bps
                pip = 0.10 if price > 100 else 0.0001
                spread_bps = (self.config.slippage_pips * pip / price) * 10_000

                impact = model.estimate(
                    order_size=quantity,
                    adv=adv if adv > 0 else bar_volume * 24,  # estimate ADV from bar vol
                    volatility_daily=vol_daily,
                    spread_bps=spread_bps,
                    price=price,
                )
                return impact.total_impact_bps / 10_000
            except ImportError:
                logger.warning("execution.market_impact not available — falling back to variable model")
                # Fall through to variable model

        if self.config.slippage_model == "fixed":
            # Gold pip = $0.10; forex pip = $0.0001.
            # Detect gold by price > $100 (gold trades ~$1500–$3000).
            pip = 0.10 if price > 100 else 0.0001
            return (self.config.slippage_pips * pip) / price

        if self.config.slippage_model in ("variable", "almgren_chriss"):
            # Base spread: 0.015% (~$0.30 at $2000 gold) — realistic for gold CFD.
            base_slippage = 0.00015
            if price > 0 and bar_high > bar_low:
                bar_range_pct = (bar_high - bar_low) / price
                # Normalise against a 1% reference range so the [0.5, 3.0] clamp
                # spans the realistic distribution of bar widths.
                ref_range_pct = 0.01  # 1% reference bar range
                multiplier = bar_range_pct / ref_range_pct
                multiplier = max(0.5, min(3.0, multiplier))
            else:
                multiplier = 1.0
            return base_slippage * multiplier * 0.5  # half-spread model

        raise ValueError(
            f"Unknown slippage_model {self.config.slippage_model!r}. "
            "Supported values: 'fixed', 'variable', 'almgren_chriss'."
        )

    def _record_trade(
        self,
        symbol: str,
        action: str,
        quantity: float,
        entry_price: float,
        exit_price: float,
        pnl: float,
        commission: float,
    ):
        """Record completed trade"""
        self.trades.append(
            {
                "timestamp": self.current_time.isoformat() if self.current_time else None,
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": pnl,
                "commission": commission,
                "net_pnl": pnl - commission,
            }
        )

    def update_prices(self, prices: dict[str, float]):
        """Update position prices for P&L calculation"""
        for symbol, price in prices.items():
            if symbol in self.positions:
                self.positions[symbol]["current_price"] = price


class BacktestEngine:
    """
    Event-driven backtesting engine

    Features:
    - Realistic execution simulation
    - Multiple strategy support
    - Performance analytics
    - Walk-forward analysis ready
    """

    #: Which look-ahead defence was in force for the most recent run.
    #: "not_run" until `run()` sets it — an unmeasured value is absent, never
    #: best-case, so a report that has not run must not read as protected.
    lookahead_protection: str = "not_run"

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.data_loader = HistoricalDataLoader()
        self.broker = SimulatedBroker(config)
        self.strategies: list[Any] = []
        self.results: BacktestResult | None = None

        # Event log
        self.events: list[dict] = []

        # Errors raised by strategies during the simulation loop. These used to
        # be logged and dropped, so a run in which every bar raised produced a
        # flat equity curve and a 0.00% return — reported as a result rather
        # than a failure. Callers can read this back after run().
        self.strategy_errors: list[str] = []

    def add_strategy(self, strategy: Any):
        """Add strategy to backtest"""
        self.strategies.append(strategy)

    async def run(self, progress_callback: Callable | None = None) -> BacktestResult:
        """
        Run backtest

        Args:
            progress_callback: Called with (current_step, total_steps, current_time)
        """
        logger.info("Starting backtest: %s to %s", self.config.start_date, self.config.end_date)

        # A backtest with no strategy attached is a misconfiguration, not a
        # 0.00% return. api/advanced_trading.py built the config, never called
        # add_strategy(), and reported the empty result as the performance of a
        # named strategy — both arms of every A/B test were this.
        if not self.strategies:
            raise ValueError(
                "No strategies added to the backtest. Call add_strategy() before run() — "
                "an empty run is a configuration error, not a flat result."
            )

        # Load data for all symbols
        all_data: dict[str, pd.DataFrame] = {}
        for symbol in self.config.symbols:
            df = await self.data_loader.load_data(symbol, "1h", self.config.start_date, self.config.end_date)
            if df is not None:
                all_data[symbol] = df
                logger.info("Loaded %s bars for %s", len(df), symbol)

        if not all_data:
            raise ValueError("No data loaded for backtest")

        # Validate all loaded DataFrames before entering the simulation loop.
        # This is the last gate before real money decisions are made on the data.
        for sym, df in list(all_data.items()):
            try:
                from data_layer.validation import validate_ohlcv

                all_data[sym] = validate_ohlcv(df, symbol=sym, strict=False, drop_bad_rows=True)
            except Exception as _ve:
                logger.warning("Backtest pre-run validation warning for %s: %s", sym, _ve)

        # Look-ahead protection.
        #
        # This block used to construct a BacktestBarGuard, log "BacktestBarGuard
        # active", and never reference it again — a control that existed, read
        # correctly, and never ran (F176). Worse, the loop below then handed the
        # strategy `all_data`: every symbol's COMPLETE frame, future bars
        # included. Measured before this change, a strategy over 120 bars read a
        # not-yet-happened bar on 119 of them and nothing objected.
        #
        # The real protection is now structural: the strategy is handed a view
        # sliced to `timestamp`, so there is no future to read. The guard is
        # kept as the second line — it refuses a reach past the cursor if a
        # strategy gets hold of the raw frame some other way.
        #
        # `lookahead_protection` records which line was actually in force, and
        # the failure path logs at WARNING rather than DEBUG: a backtest that
        # ran unpoliced must not look identical to one that did not.
        self.lookahead_protection = "point_in_time"
        _bar_guard = None
        try:
            from risk.lookahead_guard import BacktestBarGuard

            _all_ts = sorted({ts for df in all_data.values() for ts in df.get("timestamp", df.index)})
            _bar_guard = BacktestBarGuard(_all_ts)
            self.lookahead_protection = "point_in_time+guard"
            logger.info("Look-ahead protection: point-in-time slicing + BacktestBarGuard (%d bars)", len(_all_ts))
        except Exception as _bg_exc:
            logger.warning(
                "BacktestBarGuard could not be built (%s) — this run is protected by point-in-time slicing only",
                _bg_exc,
            )

        # Combine timestamps
        all_timestamps = sorted({ts for df in all_data.values() for ts in df["timestamp"]})

        # Per-symbol timestamp arrays, so each bar's cut point is a binary
        # search rather than a full-frame boolean mask. The mask form was
        # O(bars x rows) per symbol; searchsorted plus an `.iloc` view makes the
        # point-in-time slice cheap enough that there is no reason to skip it.
        _sym_stamps = {sym: df["timestamp"].to_numpy() for sym, df in all_data.items()}

        total_steps = len(all_timestamps)

        # Main backtest loop
        for i, timestamp in enumerate(all_timestamps):
            self.broker.update_time(timestamp)

            # Build the point-in-time view: every symbol's history up to and
            # including this bar, and nothing after it. This is what the
            # strategy sees, so a strategy CANNOT read a future bar rather than
            # being trusted not to.
            visible: dict[str, pd.DataFrame] = {}
            current_prices: dict[str, float] = {}
            current_bars: dict[str, dict] = {}
            for symbol, df in all_data.items():
                cut = int(np.searchsorted(_sym_stamps[symbol], timestamp, side="right"))
                if cut <= 0:
                    continue
                view = df.iloc[:cut]
                visible[symbol] = view
                row = view.iloc[-1]
                current_prices[symbol] = float(row["close"])
                current_bars[symbol] = {
                    "high": float(row.get("high", row["close"])),
                    "low": float(row.get("low", row["close"])),
                    "open": float(row.get("open", row["close"])),
                    "close": float(row["close"]),
                }

            # Update broker prices
            self.broker.update_prices(current_prices)

            # Generate signals from strategies
            for strategy in self.strategies:
                try:
                    # `visible`, not `all_data`. Passing the full frame here is
                    # what let a strategy read tomorrow's close.
                    signals = strategy.generate_signals(timestamp=timestamp, prices=current_prices, data=visible)

                    for signal in signals:
                        self._process_signal(signal, timestamp, current_prices, current_bars)

                except Exception as e:
                    logger.error("Strategy error at %s: %s", timestamp, e)
                    # Kept, not just logged. A run where this fired on every bar
                    # used to be indistinguishable from a strategy that chose
                    # not to trade.
                    self.strategy_errors.append(f"{timestamp}: {type(e).__name__}: {e}")

            # Progress callback
            if progress_callback and i % 100 == 0:
                progress_callback(i, total_steps, timestamp)

        # Calculate results
        self.results = self._calculate_results()

        logger.info("Backtest complete: %s trades", self.results.total_trades)

        return self.results

    def _kelly_position_size(
        self,
        signal: dict,
        current_price: float,
    ) -> float:
        """
        Compute position size using fractional Kelly criterion.

        Kelly fraction = (win_rate * avg_win - loss_rate * avg_loss) / avg_win
        Hard caps:
          - risk_dollars ≤ risk_per_trade * 2 * equity
          - qty * price ≤ 0.95 * available_cash  (never exceed buying power)

        Falls back to signal['size'] when kelly_fraction=0 or price=0.
        """
        if self.config.kelly_fraction <= 0 or current_price <= 0:
            return float(signal.get("size", 1.0))

        equity = self.broker.get_equity()
        available_cash = self.broker.cash

        trades = self.broker.trades
        if len(trades) < 20:
            # Not enough history — use fixed risk_per_trade with ATR stop
            stop_distance = signal.get("stop_distance", current_price * 0.01)
            if stop_distance > 0:
                risk_dollars = equity * self.config.risk_per_trade
                qty = risk_dollars / stop_distance
            else:
                qty = float(signal.get("size", 1.0))
        else:
            wins = [t["net_pnl"] for t in trades if t["net_pnl"] > 0]
            losses = [abs(t["net_pnl"]) for t in trades if t["net_pnl"] <= 0]
            if not wins or not losses:
                return float(signal.get("size", 1.0))

            win_rate = len(wins) / len(trades)
            avg_win = float(np.mean(wins))
            avg_loss = float(np.mean(losses))

            if avg_win <= 0:
                return float(signal.get("size", 1.0))

            # Full Kelly → fractional Kelly
            kelly_f = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
            kelly_f = max(0.0, kelly_f) * self.config.kelly_fraction

            risk_dollars = equity * min(kelly_f, self.config.risk_per_trade * 2)

            stop_distance = signal.get("stop_distance", current_price * 0.01)
            qty = risk_dollars / stop_distance if stop_distance > 0 else risk_dollars / current_price

        # Hard cap: never spend more than 95% of available cash
        max_qty_by_cash = (available_cash * 0.95) / current_price
        qty = min(qty, max_qty_by_cash)

        return max(0.01, round(qty, 4))

    def _process_signal(
        self,
        signal: dict,
        timestamp: datetime,
        prices: dict[str, float],
        bar_data: dict[str, dict] | None = None,
    ) -> None:
        """
        Process a trading signal.

        Applies:
        - Minimum R:R filter (config.min_rr_ratio)
        - Kelly-based position sizing (config.kelly_fraction)
        - Realistic slippage using bar high/low
        """
        symbol = signal.get("symbol")
        action = signal.get("action")

        if symbol not in prices:
            return

        current_price = prices[symbol]

        # ── R:R filter ────────────────────────────────────────────────────────
        if self.config.min_rr_ratio > 0:
            stop_dist = signal.get("stop_distance", 0.0)
            tp_dist = signal.get("tp_distance", 0.0)
            if stop_dist > 0 and tp_dist > 0:
                rr = tp_dist / stop_dist
                if rr < self.config.min_rr_ratio:
                    logger.debug(
                        "Signal rejected: R:R %.2f < min %.2f for %s",
                        rr,
                        self.config.min_rr_ratio,
                        symbol,
                    )
                    return

        # ── Position sizing ───────────────────────────────────────────────────
        # An exit closes what is actually open. Kelly sizing computes an *entry*
        # quantity from current equity, so using it to close would part-close a
        # position by an unrelated amount and leave a residual the strategy
        # never asked to hold.
        if signal.get("exit"):
            open_position = self.broker.positions.get(symbol)
            if not open_position:
                return
            quantity = float(open_position["quantity"])
            if quantity <= 0:
                return
        else:
            quantity = self._kelly_position_size(signal, current_price)

        # ── Bar high/low for variable slippage ────────────────────────────────
        bar_high = bar_low = 0.0
        if bar_data and symbol in bar_data:
            bar_high = bar_data[symbol].get("high", 0.0)
            bar_low = bar_data[symbol].get("low", 0.0)

        result = self.broker.place_market_order(
            symbol,
            action,
            quantity,
            current_price,
            bar_high=bar_high,
            bar_low=bar_low,
        )

        if result["success"]:
            self.events.append(
                {
                    "timestamp": timestamp.isoformat(),
                    "type": "order_filled",
                    "symbol": symbol,
                    "action": action,
                    "price": result["fill_price"],
                    "quantity": quantity,
                    "rr_ratio": (
                        signal.get("tp_distance", 0) / signal.get("stop_distance", 1)
                        if signal.get("stop_distance", 0) > 0
                        else None
                    ),
                }
            )

    # ------------------------------------------------------------------
    # Monte Carlo simulation
    # ------------------------------------------------------------------

    def run_monte_carlo_simulation(
        self,
        trade_returns: np.ndarray,
        n_simulations: int = 1000,
        ruin_threshold: float = 0.5,
    ) -> dict[str, float]:
        """
        Bootstrap Monte Carlo over trade returns.

        Args:
            trade_returns: Array of per-trade return fractions.
            n_simulations: Number of bootstrap paths.
            ruin_threshold: Equity fraction below which a path is considered ruined.

        Returns:
            Dict with mc_median_final, mc_p5_final, mc_p95_final, mc_ruin_probability.
        """
        if len(trade_returns) == 0:
            return {
                "mc_median_final": 1.0,
                "mc_p5_final": 1.0,
                "mc_p95_final": 1.0,
                "mc_ruin_probability": 0.0,
            }

        n_trades = len(trade_returns)
        rng = np.random.default_rng()  # unseeded — Monte Carlo bootstrap uses non-deterministic sampling
        final_equities: list[float] = []
        ruin_count = 0

        for _ in range(n_simulations):
            sampled = rng.choice(trade_returns, size=n_trades, replace=True)
            equity = 1.0
            ruined = False
            for r in sampled:
                equity *= 1.0 + r
                if equity <= ruin_threshold:
                    ruined = True
                    break
            if ruined:
                ruin_count += 1
                final_equities.append(ruin_threshold)
            else:
                final_equities.append(equity)

        arr = np.array(final_equities)
        return {
            "mc_median_final": float(np.median(arr)),
            "mc_p5_final": float(np.percentile(arr, 5)),
            "mc_p95_final": float(np.percentile(arr, 95)),
            "mc_ruin_probability": ruin_count / n_simulations,
        }

    # ------------------------------------------------------------------
    # Regime classification
    # ------------------------------------------------------------------

    def _classify_regime(
        self,
        equity_curve: list[dict],
        entry_idx: int,
        lookback: int = 60,
    ) -> str:
        """
        Classify the market regime at a trade entry using a 60-bar return lookback.

        Regimes:
          trending_bull  — positive trend, low volatility
          trending_bear  — negative trend, low volatility
          high_vol       — high volatility regardless of direction
          ranging        — low trend, low volatility
        """
        start = max(0, entry_idx - lookback)
        window = equity_curve[start : entry_idx + 1]
        if len(window) < 2:
            return "ranging"

        prices = np.array([e["equity"] for e in window])
        returns = np.diff(prices) / prices[:-1]
        if len(returns) == 0:
            return "ranging"

        trend = float(np.mean(returns))
        vol = float(np.std(returns))
        vol_threshold = 0.005  # 0.5% per bar

        if vol > vol_threshold:
            return "high_vol"
        if trend > 0.001:
            return "trending_bull"
        if trend < -0.001:
            return "trending_bear"
        return "ranging"

    def _compute_regime_breakdown(
        self,
        trades: list[dict],
        equity_curve: list[dict],
    ) -> dict[str, Any]:
        """
        Compute per-regime win_rate and avg_pnl across all trades.
        Each trade's entry regime is classified using the equity curve index.
        """
        regime_trades: dict[str, list[float]] = {
            "trending_bull": [],
            "trending_bear": [],
            "ranging": [],
            "high_vol": [],
        }

        for i, trade in enumerate(trades):
            regime = self._classify_regime(equity_curve, i)
            regime_trades[regime].append(trade.get("net_pnl", 0.0))

        breakdown: dict[str, Any] = {}
        for regime, pnls in regime_trades.items():
            if not pnls:
                continue
            arr = np.array(pnls)
            breakdown[regime] = {
                "count": len(arr),
                "win_rate": float(np.mean(arr > 0)),
                "avg_pnl": float(np.mean(arr)),
            }
        return breakdown

    # ------------------------------------------------------------------
    # Main results calculation
    # ------------------------------------------------------------------

    @staticmethod
    def _downside_deviation(returns, target: float = 0.0) -> float:
        """Root-mean-square shortfall below *target*, over ALL periods.

        Retained under its original name because this is where F120 was fixed
        and callers reference it, but the definition now lives in
        ``analytics.ratios`` so the five other modules that compute a Sortino
        share it rather than each keeping their own. See that module for why
        ``returns[returns < 0].std()`` is not a biased Sortino but a different
        statistic.
        """
        from analytics.ratios import downside_deviation

        return downside_deviation(returns, target=target)

    def _annualised_return(self, total_return: float, n_bars: int) -> float:
        """Annualise a total return over *n_bars* bars.

        The exponent is 252 / (trading days elapsed). ``n_bars`` is a BAR count
        and the engine runs on hourly bars, so dividing by ``bars_per_day`` is
        what turns one into the other. Omitting it — as this line did — reported
        a year that doubled capital as +2.93% and made Calmar meaningless
        (F119). The same function divides by ``bars_per_day`` correctly for the
        Sharpe annualisation and the average hold time; this was the one place
        it was left out.
        """
        days = n_bars / max(float(self.config.bars_per_day), 1e-9)
        return (1 + total_return) ** (252.0 / max(days, 1e-9)) - 1

    @staticmethod
    def _calmar(annual_return: float, max_drawdown: float) -> float:
        """Annualised return over maximum drawdown; 0.0 when there is no drawdown."""
        return float(annual_return / max_drawdown) if max_drawdown > 0 else 0.0

    def _calculate_results(self) -> BacktestResult:
        """Calculate performance metrics including all Area 1 additions."""
        trades = self.broker.trades

        if not trades:
            return BacktestResult(
                total_return=0,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0,
                profit_factor=0,
                max_drawdown=0,
                sharpe_ratio=0,
                equity_curve=self.broker.equity_curve,
                trades=[],
                metrics={},
            )

        # ── Basic stats ───────────────────────────────────────────────
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t["net_pnl"] > 0)
        losing_trades = total_trades - winning_trades
        win_rate = winning_trades / total_trades if total_trades > 0 else 0

        total_pnl = sum(t["net_pnl"] for t in trades)
        gross_profit = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
        gross_loss = sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0)
        profit_factor = abs(gross_profit / gross_loss) if gross_loss != 0 else float("inf")

        initial_equity = self.config.initial_capital
        final_equity = self.broker.get_equity()
        total_return = (final_equity - initial_equity) / initial_equity

        # ── Drawdown ──────────────────────────────────────────────────
        equity_values = [e["equity"] for e in self.broker.equity_curve]
        peak = initial_equity
        max_drawdown = 0.0
        for equity in equity_values:
            peak = max(peak, equity)
            dd = (peak - equity) / peak if peak > 0 else 0.0
            max_drawdown = max(max_drawdown, dd)

        # ── Bar returns (used for Sortino/Omega/Tail only) ────────────
        # NOTE: bar-level Sharpe is intentionally NOT used as the primary
        # Sharpe.  Flat no-trade bars inflate the bar-level Sharpe by
        # suppressing the denominator (std of returns).  The corrected
        # Sharpe is computed at trade level below.
        ann_factor = np.sqrt(252.0 * max(self.config.bars_per_day, 1e-9))
        bar_returns = np.array([])
        if len(equity_values) > 1:
            eq_arr = np.nan_to_num(np.array(equity_values, dtype=float), nan=0.0)
            bar_returns = np.diff(eq_arr) / np.where(eq_arr[:-1] != 0, eq_arr[:-1], 1.0)

        # ── Trade-level Sharpe (primary — corrected method) ───────────
        # mean(net_pnl) / std(net_pnl) * sqrt(252 / avg_hold_days)
        # This is the credible number reported in performance.json.
        # Bar-level Sharpe (previously reported as 4.68) was inflated by
        # flat no-trade days suppressing the return std.
        sharpe = 0.0
        sharpe_se = 0.0
        trade_pnls = np.array([t["net_pnl"] for t in trades], dtype=float)
        if len(trade_pnls) >= 2 and np.std(trade_pnls) > 0:
            # Estimate average hold time in days from equity curve length
            n_bars = len(equity_values)
            avg_hold_bars = n_bars / max(total_trades, 1)
            avg_hold_days = avg_hold_bars / self.config.bars_per_day
            trade_ann_factor = np.sqrt(252.0 / max(avg_hold_days, 0.04))
            trade_pnls_safe = np.nan_to_num(trade_pnls, nan=0.0)
            sharpe = float(
                np.mean(trade_pnls_safe) / max(float(np.std(trade_pnls_safe, ddof=1)), 1e-9) * trade_ann_factor
            )
            # Sharpe standard error: 1/sqrt(2*(N-1)) for iid returns
            sharpe_se = float(1.0 / np.sqrt(max(2.0 * (len(trade_pnls) - 1), 1e-9)))

        # ── Sortino (bar-level — acceptable for downside deviation) ───
        sortino = 0.0
        if len(bar_returns) > 0:
            downside_dev = self._downside_deviation(bar_returns)
            if downside_dev > 0:
                sortino = float(np.mean(bar_returns) / downside_dev * ann_factor)

        # ── Calmar ────────────────────────────────────────────────────
        annual_return = self._annualised_return(total_return, len(equity_values))
        calmar = self._calmar(annual_return, max_drawdown)

        # ── Omega ─────────────────────────────────────────────────────
        threshold = 0.0
        gains = bar_returns[bar_returns > threshold] - threshold
        losses = threshold - bar_returns[bar_returns <= threshold]
        omega = float(np.sum(gains) / np.sum(losses)) if np.sum(losses) > 0 else float("inf")

        # ── Tail ratio ────────────────────────────────────────────────
        tail_ratio = 0.0
        if len(bar_returns) > 0:
            p95 = abs(float(np.percentile(bar_returns, 95)))
            p5 = abs(float(np.percentile(bar_returns, 5)))
            tail_ratio = p95 / p5 if p5 > 0 else 0.0

        # ── Skewness / Kurtosis ───────────────────────────────────────
        skewness = 0.0
        kurtosis = 0.0
        if len(bar_returns) > 3:
            if SCIPY_AVAILABLE and _scipy_stats is not None:
                skewness = float(_scipy_stats.skew(bar_returns))
                kurtosis = float(_scipy_stats.kurtosis(bar_returns))
            else:
                skewness = float(pd.Series(bar_returns).skew())
                kurtosis = float(pd.Series(bar_returns).kurtosis())

        # ── MAE / MFE ─────────────────────────────────────────────────
        # Approximate: MAE = avg losing trade magnitude, MFE = avg winning trade magnitude
        avg_mae = abs(gross_loss / losing_trades) if losing_trades > 0 else 0.0
        avg_mfe = gross_profit / winning_trades if winning_trades > 0 else 0.0

        # ── Statistical significance (t-test vs 0) ────────────────────
        trade_returns_arr = np.array([t["net_pnl"] for t in trades])
        t_stat = p_val = 0.0
        is_significant = False
        sample_size = len(trade_returns_arr)

        if sample_size < 100:
            logger.warning(
                "Backtest significance test: sample_size=%d < 100 — results may not be reliable",
                sample_size,
            )

        if sample_size >= 2:
            if SCIPY_AVAILABLE and _scipy_stats is not None:
                t_result = _scipy_stats.ttest_1samp(trade_returns_arr, popmean=0.0)
                t_stat = float(t_result.statistic)
                p_val = float(t_result.pvalue)
                is_significant = bool(p_val < 0.05)
            else:
                # Manual t-statistic
                trade_returns_arr = np.nan_to_num(trade_returns_arr, nan=0.0)
                mean_r = float(np.mean(trade_returns_arr))
                std_r = float(np.std(trade_returns_arr, ddof=1))
                if std_r > 0:
                    t_stat = mean_r / (std_r / np.sqrt(max(sample_size, 1)))

        # ── Monte Carlo bootstrap (production-grade) ──────────────────
        # Uses analytics.monte_carlo for bootstrap resampling with
        # confidence intervals on Sharpe, drawdown, CAGR, and ruin prob.
        # Falls back to the internal simple MC if the module is unavailable.
        try:
            from analytics.monte_carlo import run_bootstrap

            _mc_result = run_bootstrap(
                trade_pnls=[t.get("net_pnl", 0.0) for t in trades],
                initial_capital=initial_equity,
                n_paths=int(os.getenv("MC_N_PATHS", "5000")),
                method="iid",
            )
            mc = {
                "mc_median_final": _mc_result.final_equity_ci_95[0],
                "mc_p5_final": _mc_result.final_equity_ci_95[0],
                "mc_p95_final": _mc_result.final_equity_ci_95[1],
                "mc_ruin_probability": _mc_result.ruin_probability,
                "mc_sharpe_ci_95_lower": _mc_result.sharpe_ci_95[0],
                "mc_sharpe_ci_95_upper": _mc_result.sharpe_ci_95[1],
                "mc_max_dd_ci_95_lower": _mc_result.max_dd_ci_95[0],
                "mc_max_dd_ci_95_upper": _mc_result.max_dd_ci_95[1],
                "mc_sharpe_positive_fraction": _mc_result.sharpe_positive_fraction,
                "mc_probability_of_profit": _mc_result.probability_of_profit,
                "mc_expected_shortfall_5pct": _mc_result.expected_shortfall_5pct,
                "mc_sharpe_se": _mc_result.sharpe_se,
                "mc_n_paths": _mc_result.n_paths,
            }
        except Exception as _mc_exc:
            logger.warning("Bootstrap MC failed, using simple MC: %s", _mc_exc)
            trade_return_fracs = trade_returns_arr / initial_equity
            mc = self.run_monte_carlo_simulation(trade_return_fracs)

        # ── Regime breakdown ──────────────────────────────────────────
        regime_breakdown = self._compute_regime_breakdown(trades, self.broker.equity_curve)

        # ── Aggregate metrics dict ────────────────────────────────────
        metrics: dict[str, Any] = {
            "avg_trade_pnl": total_pnl / total_trades,
            "avg_winning_trade": gross_profit / winning_trades if winning_trades > 0 else 0,
            "avg_losing_trade": gross_loss / losing_trades if losing_trades > 0 else 0,
            "max_consecutive_wins": self._max_consecutive(trades, "win"),
            "max_consecutive_losses": self._max_consecutive(trades, "loss"),
            "recovery_factor": total_return / max_drawdown if max_drawdown > 0 else 0,
            "sortino_ratio": sortino,
            "calmar_ratio": calmar,
            "omega_ratio": omega,
            "tail_ratio": tail_ratio,
            "skewness": skewness,
            "kurtosis": kurtosis,
            "avg_mae": avg_mae,
            "avg_mfe": avg_mfe,
            "t_statistic": t_stat,
            "p_value": p_val,
            "is_significant": is_significant,
            "sample_size": sample_size,
            # Trade-level Sharpe metadata
            "sharpe_trade_level": sharpe,
            "sharpe_se": sharpe_se,
            "sharpe_note": (
                f"Trade-level Sharpe: mean(net_pnl)/std(net_pnl)*sqrt(252/avg_hold_days). "
                f"N={total_trades} — SE≈±{sharpe_se:.2f}. "
                + (
                    "Statistically robust (N≥250)."
                    if total_trades >= 250
                    else "Not statistically robust — use OOS accuracy as credible number."
                )
            ),
            **{f"mc_{k}": v for k, v in mc.items()},
        }

        return BacktestResult(
            total_return=total_return,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            sharpe_se=sharpe_se,
            equity_curve=self.broker.equity_curve,
            trades=trades,
            metrics=metrics,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            omega_ratio=omega,
            tail_ratio=tail_ratio,
            skewness=skewness,
            kurtosis=kurtosis,
            avg_mae=avg_mae,
            avg_mfe=avg_mfe,
            t_statistic=t_stat,
            p_value=p_val,
            is_significant=is_significant,
            sample_size=sample_size,
            mc_median_final=mc["mc_median_final"],
            mc_p5_final=mc["mc_p5_final"],
            mc_p95_final=mc["mc_p95_final"],
            mc_ruin_probability=mc["mc_ruin_probability"],
            regime_breakdown=regime_breakdown,
        )

    def _max_consecutive(self, trades: list[dict], trade_type: str) -> int:
        """Calculate max consecutive wins or losses"""
        max_streak = 0
        current_streak = 0

        for trade in trades:
            is_win = trade["net_pnl"] > 0

            if (trade_type == "win" and is_win) or (trade_type == "loss" and not is_win):
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0

        return max_streak

    def generate_report(self) -> str:
        """Generate human-readable backtest report"""
        if not self.results:
            return "No backtest results available"

        r = self.results

        se_str = f"±{r.sharpe_se:.2f}" if r.sharpe_se > 0 else "n/a"
        robust_str = "✅ robust" if r.total_trades >= 250 else f"⚠️  N={r.total_trades} (need ≥250)"
        report = f"""
╔════════════════════════════════════════════════════════════════╗
║                    HOPEFX BACKTEST REPORT                       ║
╠════════════════════════════════════════════════════════════════╣
║ Period:     {self.config.start_date.strftime("%Y-%m-%d")} to {self.config.end_date.strftime("%Y-%m-%d")}          ║
║ Symbols:    {", ".join(self.config.symbols)}                          ║
║ Initial:    ${self.config.initial_capital:,.2f}                                  ║
╠════════════════════════════════════════════════════════════════╣
║ PERFORMANCE                                                    ║
║   Total Return:      {r.total_return * 100:>10.2f}%                            ║
║   Final Equity:      ${r.equity_curve[-1]["equity"] if r.equity_curve else 0:>10,.2f}                          ║
║   Sharpe (trade):    {r.sharpe_ratio:>10.2f}  SE {se_str:<8}                   ║
║   Sharpe robust:     {robust_str:<40}║
║   Max Drawdown:      {r.max_drawdown * 100:>10.2f}%                            ║
║   Sortino:           {r.sortino_ratio:>10.2f}                            ║
║   Calmar:            {r.calmar_ratio:>10.2f}                            ║
╠════════════════════════════════════════════════════════════════╣
║ TRADE STATISTICS                                               ║
║   Total Trades:      {r.total_trades:>10}                             ║
║   Win Rate:          {r.win_rate * 100:>10.1f}%                            ║
║   Profit Factor:     {r.profit_factor:>10.2f}                            ║
║   Avg Trade P&L:     ${r.metrics.get("avg_trade_pnl", 0):>10.2f}                          ║
║   Avg Win:           ${r.metrics.get("avg_winning_trade", 0):>10.2f}                          ║
║   Avg Loss:          ${r.metrics.get("avg_losing_trade", 0):>10.2f}                          ║
╠════════════════════════════════════════════════════════════════╣
║ ADVANCED METRICS                                               ║
║   Recovery Factor:   {r.metrics.get("recovery_factor", 0):>10.2f}                            ║
║   Max Consec Wins:   {r.metrics.get("max_consecutive_wins", 0):>10}                             ║
║   Max Consec Losses: {r.metrics.get("max_consecutive_losses", 0):>10}                             ║
║   MC Median Final:   {r.mc_median_final:>10.3f}x                           ║
║   MC P5 Final:       {r.mc_p5_final:>10.3f}x                           ║
║   MC Ruin Prob:      {r.mc_ruin_probability * 100:>10.1f}%                            ║
╚════════════════════════════════════════════════════════════════╝
NOTE: Sharpe is trade-level (corrected). Bar-level Sharpe is inflated
      by flat no-trade days and is NOT reported here.
        """

        return report

    def export_to_json(self, filepath: str):
        """Export results to JSON"""
        if not self.results:
            raise ValueError("No results to export")

        data = {
            "config": {
                "start_date": self.config.start_date.isoformat(),
                "end_date": self.config.end_date.isoformat(),
                "symbols": self.config.symbols,
                "initial_capital": self.config.initial_capital,
            },
            "results": {
                "total_return": self.results.total_return,
                "total_trades": self.results.total_trades,
                "win_rate": self.results.win_rate,
                "profit_factor": self.results.profit_factor,
                "max_drawdown": self.results.max_drawdown,
                "sharpe_ratio": self.results.sharpe_ratio,
                "metrics": self.results.metrics,
            },
            "equity_curve": self.results.equity_curve,
            "trades": self.results.trades,
        }

        with Path(filepath).open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

        logger.info("Backtest results exported to %s", filepath)


# Convenience functions
async def run_backtest(
    strategy: Any,
    symbols: list[str],
    start_date: datetime,
    end_date: datetime,
    initial_capital: float = 100000.0,
) -> BacktestResult:
    """Quick backtest function"""
    config = BacktestConfig(
        start_date=start_date,
        end_date=end_date,
        symbols=symbols,
        initial_capital=initial_capital,
    )

    engine = BacktestEngine(config)
    engine.add_strategy(strategy)

    return await engine.run()
