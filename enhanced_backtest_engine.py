# ============================================================================
# FIXED: enhanced_backtest_engine.py - PROPER PYTHON MODULE
# ============================================================================

"""
Enhanced Backtesting Engine with Tick-Level Precision & Realistic Market Impact
Institutional-grade backtesting with proper slippage, spread modeling, and transaction costs.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Tuple, Any
from enum import Enum
from datetime import datetime, timedelta
import logging
from collections import deque
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ExecutionModel(Enum):
    """Market execution quality models"""
    IDEAL = "ideal"  # No slippage, mid-price fills (unrealistic)
    CONSERVATIVE = "conservative"  # Small slippage, realistic for liquid pairs
    AGGRESSIVE = "aggressive"  # Higher slippage, volatile markets
    PESSIMISTIC = "pessimistic"  # Worst-case scenario modeling

@dataclass
class TickData:
    """Tick-level market data with full depth simulation"""
    timestamp: datetime
    bid: float
    ask: float
    bid_size: float = 0.0
    ask_size: float = 0.0
    volume: float = 0.0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def spread_pct(self) -> float:
        return self.spread / self.mid if self.mid > 0 else 0

@dataclass
class TransactionCosts:
    """Comprehensive transaction cost model"""
    spread_pips: float = 0.0  # Variable spread model
    commission_per_lot: float = 0.0  # Broker commission
    slippage_model: ExecutionModel = ExecutionModel.CONSERVATIVE

    # Market impact coefficients (square-root model)
    impact_coefficient: float = 0.1  # Almgren-Chriss style

    def calculate_slippage(self, order_size: float, volatility: float,
                          execution_model: ExecutionModel) -> float:
        """
        Calculate realistic slippage based on order size and market conditions.
        Uses square-root market impact model: impact = coeff * sigma * sqrt(order_size)
        """
        base_slippage = {
            ExecutionModel.IDEAL: 0.0,
            ExecutionModel.CONSERVATIVE: 0.1,  # 0.1 pips average
            ExecutionModel.AGGRESSIVE: 0.5,  # 0.5 pips
            ExecutionModel.PESSIMISTIC: 1.5  # 1.5 pips (news events)
        }.get(execution_model, 0.1)

        # Scale with order size (larger orders = more impact)
        size_factor = np.sqrt(abs(order_size)) * self.impact_coefficient

        # Scale with volatility (higher vol = more slippage)
        vol_factor = 1 + (volatility * 10)  # 10% vol adds 100% to slippage

        return base_slippage * size_factor * vol_factor

    def total_cost_per_unit(self, order_size: float, volatility: float,
                           execution_model: ExecutionModel) -> float:
        """Total transaction cost in price units"""
        slippage = self.calculate_slippage(order_size, volatility, execution_model)
        spread_cost = self.spread_pips * 0.0001  # Convert pips to price
        commission = self.commission_per_lot / 100000  # Per unit
        return spread_cost + slippage + commission

@dataclass
class Position:
    """Track position with detailed P&L attribution"""
    symbol: str
    size: float = 0.0
    avg_entry: float = 0.0
    entry_time: Optional[datetime] = None

    # Cost tracking
    total_commission: float = 0.0
    total_slippage: float = 0.0

    # Risk metrics
    max_favorable_excursion: float = 0.0  # Best price reached
    max_adverse_excursion: float = 0.0  # Worst price reached (drawdown)

    def update_mfe_mae(self, current_price: float):
        """Update max favorable/adverse excursion"""
        if self.size > 0:  # Long
            self.max_favorable_excursion = max(self.max_favorable_excursion,
                                               current_price - self.avg_entry)
            self.max_adverse_excursion = max(self.max_adverse_excursion,
                                             self.avg_entry - current_price)
        elif self.size < 0:  # Short
            self.max_favorable_excursion = max(self.max_favorable_excursion,
                                               self.avg_entry - current_price)
            self.max_adverse_excursion = max(self.max_adverse_excursion,
                                             current_price - self.avg_entry)

@dataclass
class Trade:
    """Complete trade record with full cost attribution"""
    entry_time: datetime
    exit_time: datetime
    symbol: str
    direction: str  # 'long' or 'short'
    entry_price: float
    exit_price: float
    size: float

    # Cost breakdown
    entry_slippage: float
    exit_slippage: float
    commission: float

    # Risk metrics
    mfe: float  # Max favorable excursion
    mae: float  # Max adverse excursion

    @property
    def gross_pnl(self) -> float:
        """P&L before costs"""
        if self.direction == 'long':
            return (self.exit_price - self.entry_price) * self.size
        else:
            return (self.entry_price - self.exit_price) * self.size

    @property
    def net_pnl(self) -> float:
        """P&L after all costs"""
        return self.gross_pnl - self.entry_slippage - self.exit_slippage - self.commission

    @property
    def duration(self) -> timedelta:
        return self.exit_time - self.entry_time


class MarketRegimeDetector:
    """
    Detect market regime (trending/ranging/volatile) for adaptive strategies.
    Uses ADX, volatility percentiles, and fractal dimension.
    """

    def __init__(self, lookback: int = 50):
        self.lookback = lookback
        self.price_history: deque = deque(maxlen=lookback)
        self.regime_history: deque = deque(maxlen=100)

    def update(self, price: float) -> str:
        """Update detector and return current regime"""
        self.price_history.append(price)

        if len(self.price_history) < self.lookback:
            return "insufficient_data"

        prices = np.array(self.price_history)

        # Calculate indicators
        adx = self._calculate_adx(prices)
        volatility = self._calculate_volatility(prices)
        hurst = self._estimate_hurst(prices)

        # Regime classification
        if volatility > np.percentile(list(self.price_history), 90):
            regime = "high_volatility"
        elif adx > 25 and hurst > 0.5:
            regime = "trending"
        elif adx < 20:
            regime = "ranging"
        else:
            regime = "transitional"

        self.regime_history.append(regime)
        return regime

    def _calculate_adx(self, prices: np.ndarray, period: int = 14) -> float:
        """Simplified ADX calculation"""
        if len(prices) < period + 1:
            return 0.0

        highs = prices[1:]
        lows = prices[:-1]

        # True range
        tr1 = highs - lows
        tr = np.mean(tr1[-period:])

        # Directional movement (simplified)
        plus_dm = np.sum(np.where(highs > np.roll(highs, 1), highs - np.roll(highs, 1), 0)[-period:])
        minus_dm = np.sum(np.where(lows < np.roll(lows, 1), np.roll(lows, 1) - lows, 0)[-period:])

        if tr == 0:
            return 0.0

        dx = abs(plus_dm - minus_dm) / (plus_dm + minus_dm + 1e-10) * 100
        return dx

    def _calculate_volatility(self, prices: np.ndarray) -> float:
        """Annualized volatility"""
        returns = np.diff(np.log(prices))
        if len(returns) < 2:
            return 0.0
        return np.std(returns) * np.sqrt(252 * 24 * 60)  # Annualized, assuming minute data

    def _estimate_hurst(self, prices: np.ndarray, max_lag: int = 20) -> float:
        """Hurst exponent estimation using R/S analysis"""
        lags = range(2, min(max_lag, len(prices) // 4))
        tau = [np.std(np.subtract(prices[lag:], prices[:-lag])) for lag in lags]

        if len(tau) < 2 or any(t == 0 for t in tau):
            return 0.5

        # Linear regression on log-log
        log_lags = np.log(list(lags))
        log_tau = np.log(tau)

        # Slope = Hurst exponent
        slope = np.polyfit(log_lags, log_tau, 1)[0]
        return slope

    def get_regime_stability(self) -> float:
        """How long current regime has persisted (0-1)"""
        if len(self.regime_history) < 10:
            return 0.0

        current = self.regime_history[-1]
        same_regime_count = 0
        for regime in reversed(self.regime_history):
            if regime == current:
                same_regime_count += 1
            else:
                break

        return min(same_regime_count / 20, 1.0)  # Normalize to 20 periods


class RiskManager:
    """
    Institutional-grade risk management with Kelly criterion,
    risk of ruin calculations, and dynamic position sizing.
    """

    def __init__(self,
                 initial_capital: float = 100000.0,
                 max_risk_per_trade: float = 0.02,  # 2% per trade
                 max_total_risk: float = 0.06,  # 6% total exposure
                 kelly_fraction: float = 0.5):  # Half-Kelly for safety
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.max_risk_per_trade = max_risk_per_trade
        self.max_total_risk = max_total_risk
        self.kelly_fraction = kelly_fraction

        self.trade_history: List[Trade] = []
        self.peak_capital = initial_capital
        self.current_drawdown = 0.0

    def update_capital(self, pnl: float):
        """Update capital and track drawdown"""
        self.current_capital += pnl
        self.peak_capital = max(self.peak_capital, self.current_capital)
        self.current_drawdown = (self.peak_capital - self.current_capital) / self.peak_capital

    def calculate_kelly_fraction(self) -> float:
        """
        Calculate optimal Kelly fraction based on trade history.
        f* = (bp - q) / b
        where b = avg win/avg loss, p = win rate, q = 1-p
        """
        if len(self.trade_history) < 20:
            return self.kelly_fraction

        wins = [t.net_pnl for t in self.trade_history if t.net_pnl > 0]
        losses = [abs(t.net_pnl) for t in self.trade_history if t.net_pnl < 0]

        if not wins or not losses:
            return 0.0

        p = len(wins) / len(self.trade_history)
        q = 1 - p
        b = np.mean(wins) / np.mean(losses)

        kelly = (b * p - q) / b if b > 0 else 0
        return max(0, min(kelly, 0.5)) * self.kelly_fraction  # Cap at half-Kelly

    def calculate_risk_of_ruin(self,
                               win_rate: float = None,
                               avg_win: float = None,
                               avg_loss: float = None,
                               num_simulations: int = 10000) -> float:
        """
        Monte Carlo simulation to estimate risk of ruin (losing X% of capital).
        """
        if win_rate is None:
            if len(self.trade_history) < 30:
                return 0.5  # Unknown = risky
            wins = [t.net_pnl for t in self.trade_history if t.net_pnl > 0]
            losses = [t.net_pnl for t in self.trade_history if t.net_pnl < 0]
            win_rate = len(wins) / len(self.trade_history)
            avg_win = np.mean(wins) if wins else 0
            avg_loss = abs(np.mean(losses)) if losses else 1

        ruin_threshold = self.current_capital * 0.5  # 50% capital loss = ruin

        ruins = 0
        for _ in range(num_simulations):
            capital = self.current_capital
            trades = 0

            while capital > ruin_threshold and trades < 1000:
                if np.random.random() < win_rate:
                    capital += avg_win
                else:
                    capital -= avg_loss
                trades += 1

            if capital <= 0:
                ruins += 1
                break

        return ruins / num_simulations

    def get_position_size(self,
                          entry_price: float,
                          stop_loss: float,
                          volatility: float,
                          use_kelly: bool = True) -> float:
        """
        Calculate position size using volatility-adjusted Kelly or fixed fractional.
        """
        # Base risk amount
        risk_amount = self.current_capital * self.max_risk_per_trade

        if use_kelly:
            kelly = self.calculate_kelly_fraction()
            risk_amount *= (1 + kelly)  # Scale by Kelly

        # Adjust for volatility (higher vol = smaller size)
        vol_adjustment = 1 / (1 + volatility * 5)  # 20% vol = 50% size reduction
        risk_amount *= vol_adjustment

        # Calculate units based on stop distance
        stop_distance = abs(entry_price - stop_loss)
        if stop_distance == 0:
            return 0.0

        position_size = risk_amount / stop_distance

        # Check total exposure limit
        current_exposure = sum(abs(p.size * p.avg_entry) for p in self.get_positions())
        max_new_exposure = self.current_capital * self.max_total_risk - current_exposure

        max_size_by_exposure = max_new_exposure / entry_price if entry_price > 0 else 0

        return min(position_size, max_size_by_exposure)

    def get_positions(self) -> List[Position]:
        """Get current open positions"""
        return []  # Implemented in backtest engine


class EnhancedBacktestEngine:
    """
    Production-grade backtesting with tick-level precision,
    realistic execution, and comprehensive risk metrics.
    """

    def __init__(self,
                 initial_capital: float = 100000.0,
                 transaction_costs: TransactionCosts = None,
                 execution_model: ExecutionModel = ExecutionModel.CONSERVATIVE):

        self.initial_capital = initial_capital
        self.transaction_costs = transaction_costs or TransactionCosts()
        self.execution_model = execution_model

        # State
        self.capital = initial_capital
        self.peak_capital = initial_capital
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.equity_curve: List[Tuple[datetime, float]] = []

        # Risk management
        self.risk_manager = RiskManager(initial_capital)
        self.regime_detector = MarketRegimeDetector()

        # Market state
        self.current_regime = "insufficient_data"
        self.current_volatility = 0.0

        logger.info(f"EnhancedBacktestEngine initialized with {execution_model.value} execution")

    def process_tick(self, tick: TickData, timestamp: datetime):
        """Process a single tick with full execution simulation"""

        # Update market regime
        self.current_regime = self.regime_detector.update(tick.mid)

        # Calculate rolling volatility
        if len(self.regime_detector.price_history) > 20:
            returns = np.diff(np.log(list(self.regime_detector.price_history)[-20:]))
            self.current_volatility = np.std(returns) * np.sqrt(252 * 24 * 60)

        # Update open positions MFE/MAE
        for pos in self.positions.values():
            pos.update_mfe_mae(tick.mid)

        # Record equity
        current_equity = self._calculate_equity(tick)
        self.equity_curve.append((timestamp, current_equity))

        # Update peak and drawdown
        self.peak_capital = max(self.peak_capital, current_equity)

        return current_equity

    def _calculate_equity(self, tick: TickData) -> float:
        """Calculate total equity including unrealized P&L"""
        equity = self.capital
        for pos in self.positions.values():
            if pos.size > 0:
                equity += pos.size * (tick.bid - pos.avg_entry)  # Use bid for longs
            else:
                equity += pos.size * (pos.avg_entry - tick.ask)  # Use ask for shorts
        return equity

    def execute_order(self,
                      symbol: str,
                      size: float,
                      tick: TickData,
                      timestamp: datetime,
                      order_type: str = "market") -> Tuple[bool, Dict]:
        """
        Execute order with realistic slippage and transaction costs.
        Returns (success, execution_details)
        """

        # Determine fill price based on direction and execution quality
        if size > 0:  # Buy
            base_price = tick.ask
            # Slippage moves price against us (higher for buys)
            slippage = self.transaction_costs.calculate_slippage(
                size, self.current_volatility, self.execution_model
            )
            fill_price = base_price + slippage * 0.0001  # Convert pips to price
        else:  # Sell
            base_price = tick.bid
            slippage = self.transaction_costs.calculate_slippage(
                size, self.current_volatility, self.execution_model
            )
            fill_price = base_price - slippage * 0.0001

        # Calculate costs
        commission = abs(size) * self.transaction_costs.commission_per_lot / 100000
        spread_cost = abs(size) * tick.spread * 0.5  # Half spread per side

        # Update or create position
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)

        pos = self.positions[symbol]

        # Check if this is a reversal or close
        if pos.size * size < 0:  # Opposite directions = close/reduce
            # Calculate realized P&L
            if abs(size) >= abs(pos.size):  # Full close or reversal
                realized_pnl = self._close_position(pos, fill_price, size, timestamp, slippage, commission)
                self.capital += realized_pnl
                self.risk_manager.update_capital(realized_pnl)

                if abs(size) > abs(pos.size):  # Reversal
                    remaining = size + pos.size  # pos.size is negative for short
                    pos.size = remaining
                    pos.avg_entry = fill_price
                    pos.entry_time = timestamp
                    pos.total_slippage = slippage
                    pos.total_commission = commission
                else:
                    del self.positions[symbol]
            else:  # Partial close
                realized_pnl = self._close_position_partial(pos, fill_price, size, timestamp, slippage, commission)
                self.capital += realized_pnl
                self.risk_manager.update_capital(realized_pnl)
        else:  # Adding to position
            # Update average entry
            total_size = pos.size + size
            if total_size != 0:
                pos.avg_entry = (pos.size * pos.avg_entry + size * fill_price) / total_size
                pos.size = total_size
                pos.total_slippage += slippage
                pos.total_commission += commission

        return True, {
            "fill_price": fill_price,
            "slippage": slippage,
            "commission": commission,
            "spread_cost": spread_cost,
            "regime": self.current_regime,
            "volatility": self.current_volatility
        }

    def _close_position(self, pos: Position, exit_price: float,
                        closing_size: float, timestamp: datetime,
                        slippage: float, commission: float) -> float:
        """Close position and record trade"""

        # Calculate P&L
        if pos.size > 0:  # Long
            gross_pnl = (exit_price - pos.avg_entry) * abs(pos.size)
        else:  # Short
            gross_pnl = (pos.avg_entry - exit_price) * abs(pos.size)

        net_pnl = gross_pnl - pos.total_slippage - pos.total_commission - slippage - commission

        # Record trade
        trade = Trade(
            entry_time=pos.entry_time,
            exit_time=timestamp,
            symbol=pos.symbol,
            direction='long' if pos.size > 0 else 'short',
            entry_price=pos.avg_entry,
            exit_price=exit_price,
            size=abs(pos.size),
            entry_slippage=pos.total_slippage,
            exit_slippage=slippage,
            commission=pos.total_commission + commission,
            mfe=pos.max_favorable_excursion,
            mae=pos.max_adverse_excursion
        )

        self.trades.append(trade)
        self.risk_manager.trade_history.append(trade)

        return net_pnl

    def get_performance_report(self) -> Dict:
        """Generate comprehensive performance analytics"""

        if not self.trades:
            return {"error": "No trades executed"}

        pnls = [t.net_pnl for t in self.trades]
        gross_pnls = [t.gross_pnl for t in self.trades]
        durations = [(t.exit_time - t.entry_time).total_seconds() / 60 for t in self.trades]  # minutes

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        # Core metrics
        total_return = (self.capital - self.initial_capital) / self.initial_capital

        # Risk metrics
        equity_values = [e[1] for e in self.equity_curve]
        returns = np.diff(equity_values) / equity_values[:-1]

        # Sharpe ratio (assuming risk-free rate = 0 for simplicity)
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252 * 24 * 60)  # Annualized
        else:
            sharpe = 0.0

        # Max drawdown
        peak = self.initial_capital
        max_dd = 0.0
        for equity in equity_values:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak
            max_dd = max(max_dd, dd)

        # Cost attribution
        total_slippage = sum(t.entry_slippage + t.exit_slippage for t in self.trades)
        total_commission = sum(t.commission for t in self.trades)
        total_costs = total_slippage + total_commission

        return {
            "summary": {
                "total_trades": len(self.trades),
                "win_rate": len(wins) / len(pnls) if pnls else 0,
                "profit_factor": abs(sum(wins) / sum(losses)) if losses else float('inf'),
                "total_return_pct": total_return * 100,
                "sharpe_ratio": sharpe,
                "max_drawdown_pct": max_dd * 100,
                "risk_of_ruin": self.risk_manager.calculate_risk_of_ruin()
            },
            "trade_metrics": {
                "avg_trade": np.mean(pnls),
                "avg_win": np.mean(wins) if wins else 0,
                "avg_loss": np.mean(losses) if losses else 0,
                "largest_win": max(wins) if wins else 0,
                "largest_loss": min(losses) if losses else 0,
                "avg_duration_min": np.mean(durations),
                "avg_mfe": np.mean([t.mfe for t in self.trades]),
                "avg_mae": np.mean([t.mae for t in self.trades])
            },
            "cost_analysis": {
                "total_costs": total_costs,
                "slippage_cost": total_slippage,
                "commission_cost": total_commission,
                "cost_per_trade": total_costs / len(self.trades),
                "cost_drag_pct": (total_costs / abs(sum(gross_pnls)) * 100) if gross_pnls else 0
            },
            "regime_performance": self._analyze_regime_performance(),
            "equity_curve": self.equity_curve
        }

    def _analyze_regime_performance(self) -> Dict:
        """Analyze performance by market regime"""
        return {
            "current_regime": self.current_regime,
            "regime_stability": self.regime_detector.get_regime_stability()
        }

    def _close_position_partial(self, pos: Position, exit_price: float,
                                 closing_size: float, timestamp: datetime,
                                 slippage: float, commission: float) -> float:
        """Close partial position"""
        # Calculate proportional P&L
        close_ratio = abs(closing_size) / abs(pos.size)
        
        if pos.size > 0:  # Long
            gross_pnl = (exit_price - pos.avg_entry) * abs(closing_size)
        else:  # Short
            gross_pnl = (pos.avg_entry - exit_price) * abs(closing_size)
        
        # Proportional costs
        prop_slippage = pos.total_slippage * close_ratio
        prop_commission = pos.total_commission * close_ratio
        
        net_pnl = gross_pnl - prop_slippage - prop_commission - slippage - commission
        
        # Reduce position
        pos.size += closing_size  # closing_size is negative for longs
        pos.total_slippage -= prop_slippage
        pos.total_commission -= prop_commission
        
        return net_pnl


# ============================================================================
# Example usage and testing
# ============================================================================

if __name__ == "__main__":
    # Create realistic XAUUSD tick data simulation
    np.random.seed(42)

    # Simulate 2 days of minute data
    n_ticks = 2880  # 2 days of minutes
    base_price = 1950.0

    # Generate realistic price path with volatility clustering
    returns = np.random.normal(0, 0.0001, n_ticks)
    # Add volatility clustering
    for i in range(1, n_ticks):
        returns[i] *= (1 + abs(returns[i-1]) * 5)  # GARCH-like effect

    prices = base_price * np.exp(np.cumsum(returns))

    # Create bid/ask with variable spread
    spreads = np.random.uniform(0.02, 0.08, n_ticks)  # 2-8 pips for XAUUSD
    bids = prices - spreads / 2
    asks = prices + spreads / 2

    # Initialize engine with realistic costs
    costs = TransactionCosts(
        spread_pips=3.0,  # Average 3 pips
        commission_per_lot=7.0,  # $7 per lot
        impact_coefficient=0.05
    )

    engine = EnhancedBacktestEngine(
        initial_capital=100000.0,
        transaction_costs=costs,
        execution_model=ExecutionModel.CONSERVATIVE
    )

    # Simulate simple strategy: MA crossover with regime filter
    fast_ma_period = 10
    slow_ma_period = 30
    position = 0

    for i in range(slow_ma_period, n_ticks):
        timestamp = datetime.now() + timedelta(minutes=i)

        tick = TickData(
            timestamp=timestamp,
            bid=bids[i],
            ask=asks[i],
            bid_size=1.0,
            ask_size=1.0
        )

        # Process tick
        engine.process_tick(tick, timestamp)

        # Simple MA strategy (only trade in trending regimes)
        if engine.current_regime in ["trending", "transitional"]:
            fast_ma = np.mean(prices[i-fast_ma_period:i])
            slow_ma = np.mean(prices[i-slow_ma_period:i])

            # Entry logic
            if fast_ma > slow_ma and position <= 0:
                # Buy signal
                if position < 0:
                    engine.execute_order("XAUUSD", -position, tick, timestamp)  # Close short
                size = engine.risk_manager.get_position_size(asks[i], bids[i] - 5, engine.current_volatility)
                engine.execute_order("XAUUSD", size, tick, timestamp)
                position = size

            elif fast_ma < slow_ma and position >= 0:
                # Sell signal
                if position > 0:
                    engine.execute_order("XAUUSD", -position, tick, timestamp)  # Close long
                size = engine.risk_manager.get_position_size(bids[i], asks[i] + 5, engine.current_volatility)
                engine.execute_order("XAUUSD", -size, tick, timestamp)
                position = -size

    # Generate report
    report = engine.get_performance_report()
    print(json.dumps(report["summary"], indent=2))
    print("\nCost Analysis:")
    print(json.dumps(report["cost_analysis"], indent=2))
