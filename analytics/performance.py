"""
Performance Analytics Dashboard

Comprehensive performance analytics including:
- Equity curve analysis
- Strategy comparison
- Trade statistics
- Performance attribution
- Risk metrics visualization data
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import numpy as np
import logging

logger = logging.getLogger(__name__)


class MetricPeriod(Enum):
    """Time periods for metric calculation."""
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"
    ALL_TIME = "all_time"


@dataclass
class TradeRecord:
    """Record of a completed trade."""
    id: str
    symbol: str
    strategy: str
    side: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_percent: float
    commission: float
    duration_minutes: int
    max_favorable_excursion: float
    max_adverse_excursion: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EquityPoint:
    """Single point on equity curve."""
    timestamp: datetime
    equity: float
    cash: float
    open_pnl: float
    drawdown: float
    drawdown_pct: float
    high_water_mark: float


@dataclass
class StrategyPerformance:
    """Performance metrics for a single strategy."""
    strategy_name: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    profit_factor: float
    expectancy: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    avg_trade_duration_minutes: float
    trades_per_day: float
    recovery_factor: float
    

@dataclass
class PerformanceReport:
    """Comprehensive performance report."""
    period: MetricPeriod
    start_date: datetime
    end_date: datetime
    starting_equity: float
    ending_equity: float
    total_return: float
    total_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    expectancy: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    max_drawdown_pct: float
    avg_daily_return: float
    volatility: float
    best_day: float
    worst_day: float
    longest_winning_streak: int
    longest_losing_streak: int
    trades_by_symbol: Dict[str, int]
    trades_by_strategy: Dict[str, int]
    pnl_by_symbol: Dict[str, float]
    pnl_by_strategy: Dict[str, float]
    equity_curve: List[EquityPoint]
    monthly_returns: Dict[str, float]

    def to_dict(self) -> Dict:
        return {
            'period': self.period.value,
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
            'starting_equity': self.starting_equity,
            'ending_equity': self.ending_equity,
            'total_return': self.total_return,
            'total_return_pct': self.total_return_pct,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': self.win_rate,
            'avg_win': self.avg_win,
            'avg_loss': self.avg_loss,
            'profit_factor': self.profit_factor,
            'expectancy': self.expectancy,
            'sharpe_ratio': self.sharpe_ratio,
            'sortino_ratio': self.sortino_ratio,
            'calmar_ratio': self.calmar_ratio,
            'max_drawdown': self.max_drawdown,
            'max_drawdown_pct': self.max_drawdown_pct,
            'avg_daily_return': self.avg_daily_return,
            'volatility': self.volatility,
            'best_day': self.best_day,
            'worst_day': self.worst_day,
            'longest_winning_streak': self.longest_winning_streak,
            'longest_losing_streak': self.longest_losing_streak,
            'trades_by_symbol': self.trades_by_symbol,
            'trades_by_strategy': self.trades_by_strategy,
            'pnl_by_symbol': self.pnl_by_symbol,
            'pnl_by_strategy': self.pnl_by_strategy,
            'monthly_returns': self.monthly_returns,
        }


class PerformanceAnalytics:
    """
    Comprehensive performance analytics engine.

    Features:
    - Equity curve tracking
    - Trade-by-trade analysis
    - Strategy comparison
    - Risk-adjusted metrics
    - Performance attribution
    """

    def __init__(self, initial_equity: float = 10000.0, risk_free_rate: float = 0.05):
        """
        Initialize analytics engine.

        Args:
            initial_equity: Starting account balance
            risk_free_rate: Annual risk-free rate for Sharpe calculation
        """
        self.initial_equity = initial_equity
        self.current_equity = initial_equity
        self.risk_free_rate = risk_free_rate
        
        # Trade records
        self.trades: List[TradeRecord] = []
        
        # Equity curve
        self.equity_curve: List[EquityPoint] = []
        self.high_water_mark = initial_equity
        
        # Daily returns for metric calculations
        self.daily_returns: List[float] = []
        self.daily_equity: List[Tuple[datetime, float]] = []
        
        # Initialize with starting point
        self._record_equity_point(initial_equity, 0, 0)
        
        logger.info(f"Performance Analytics initialized with equity: ${initial_equity:,.2f}")

    def record_trade(self, trade: TradeRecord):
        """Record a completed trade."""
        self.trades.append(trade)
        
        # Update equity
        self.current_equity += trade.pnl
        
        # Update high water mark
        if self.current_equity > self.high_water_mark:
            self.high_water_mark = self.current_equity
        
        # Record equity point
        drawdown = self.high_water_mark - self.current_equity
        drawdown_pct = drawdown / self.high_water_mark if self.high_water_mark > 0 else 0
        
        self._record_equity_point(
            self.current_equity,
            0,  # Open PnL would be tracked separately
            drawdown
        )
        
        logger.debug(f"Trade recorded: {trade.id} - PnL: ${trade.pnl:,.2f}")

    def _record_equity_point(self, equity: float, open_pnl: float, drawdown: float):
        """Record a point on the equity curve."""
        drawdown_pct = drawdown / self.high_water_mark if self.high_water_mark > 0 else 0
        
        point = EquityPoint(
            timestamp=datetime.utcnow(),
            equity=equity,
            cash=equity - open_pnl,
            open_pnl=open_pnl,
            drawdown=drawdown,
            drawdown_pct=drawdown_pct,
            high_water_mark=self.high_water_mark
        )
        
        self.equity_curve.append(point)
        
        # Update daily equity for return calculations
        today = datetime.utcnow().date()
        if not self.daily_equity or self.daily_equity[-1][0].date() != today:
            self.daily_equity.append((datetime.utcnow(), equity))
            
            # Calculate daily return
            if len(self.daily_equity) >= 2:
                prev_equity = self.daily_equity[-2][1]
                daily_return = (equity - prev_equity) / prev_equity if prev_equity > 0 else 0
                self.daily_returns.append(daily_return)

    def get_performance_report(self, period: MetricPeriod = MetricPeriod.ALL_TIME) -> PerformanceReport:
        """
        Generate comprehensive performance report.

        Args:
            period: Time period for analysis

        Returns:
            PerformanceReport object
        """
        # Filter trades by period
        now = datetime.utcnow()
        start_date = self._get_period_start(period, now)
        filtered_trades = [t for t in self.trades if t.exit_time >= start_date]
        
        # Calculate basic metrics
        total_trades = len(filtered_trades)
        winning_trades = [t for t in filtered_trades if t.pnl > 0]
        losing_trades = [t for t in filtered_trades if t.pnl < 0]
        
        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        win_rate = win_count / total_trades if total_trades > 0 else 0
        
        # PnL metrics
        total_pnl = sum(t.pnl for t in filtered_trades)
        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = abs(sum(t.pnl for t in losing_trades))
        
        avg_win = gross_profit / win_count if win_count > 0 else 0
        avg_loss = gross_loss / loss_count if loss_count > 0 else 0
        
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
        
        # Starting/ending equity for period
        start_equity = self.initial_equity
        if self.equity_curve:
            period_points = [p for p in self.equity_curve if p.timestamp >= start_date]
            if period_points:
                start_equity = period_points[0].equity
        end_equity = self.current_equity
        
        total_return = end_equity - start_equity
        total_return_pct = total_return / start_equity if start_equity > 0 else 0
        
        # Risk metrics
        sharpe = self._calculate_sharpe_ratio(filtered_trades)
        sortino = self._calculate_sortino_ratio(filtered_trades)
        max_dd, max_dd_pct = self._calculate_max_drawdown(period)
        calmar = (total_return_pct * 365 / max(1, (now - start_date).days)) / max_dd_pct if max_dd_pct > 0 else 0
        
        # Daily metrics
        period_returns = self._get_period_returns(start_date)
        avg_daily = np.mean(period_returns) if period_returns else 0
        volatility = np.std(period_returns) * np.sqrt(252) if period_returns else 0
        best_day = max(period_returns) if period_returns else 0
        worst_day = min(period_returns) if period_returns else 0
        
        # Streaks
        win_streak, loss_streak = self._calculate_streaks(filtered_trades)
        
        # Breakdown by symbol and strategy
        trades_by_symbol = self._group_count_by(filtered_trades, 'symbol')
        trades_by_strategy = self._group_count_by(filtered_trades, 'strategy')
        pnl_by_symbol = self._group_pnl_by(filtered_trades, 'symbol')
        pnl_by_strategy = self._group_pnl_by(filtered_trades, 'strategy')
        
        # Monthly returns
        monthly_returns = self._calculate_monthly_returns(filtered_trades)
        
        # Filter equity curve for period
        period_equity = [p for p in self.equity_curve if p.timestamp >= start_date]
        
        return PerformanceReport(
            period=period,
            start_date=start_date,
            end_date=now,
            starting_equity=start_equity,
            ending_equity=end_equity,
            total_return=total_return,
            total_return_pct=total_return_pct,
            total_trades=total_trades,
            winning_trades=win_count,
            losing_trades=loss_count,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            expectancy=expectancy,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            max_drawdown=max_dd,
            max_drawdown_pct=max_dd_pct,
            avg_daily_return=avg_daily,
            volatility=volatility,
            best_day=best_day,
            worst_day=worst_day,
            longest_winning_streak=win_streak,
            longest_losing_streak=loss_streak,
            trades_by_symbol=trades_by_symbol,
            trades_by_strategy=trades_by_strategy,
            pnl_by_symbol=pnl_by_symbol,
            pnl_by_strategy=pnl_by_strategy,
            equity_curve=period_equity,
            monthly_returns=monthly_returns
        )

    def compare_strategies(self, strategies: List[str] = None) -> Dict[str, StrategyPerformance]:
        """
        Compare performance across strategies.

        Args:
            strategies: List of strategy names to compare (None = all)

        Returns:
            Dict of strategy name to StrategyPerformance
        """
        if strategies is None:
            strategies = list(set(t.strategy for t in self.trades))
        
        results = {}
        
        for strategy in strategies:
            strategy_trades = [t for t in self.trades if t.strategy == strategy]
            
            if not strategy_trades:
                continue
            
            total = len(strategy_trades)
            winners = [t for t in strategy_trades if t.pnl > 0]
            losers = [t for t in strategy_trades if t.pnl < 0]
            
            win_count = len(winners)
            loss_count = len(losers)
            
            gross_profit = sum(t.pnl for t in winners)
            gross_loss = abs(sum(t.pnl for t in losers))
            total_pnl = sum(t.pnl for t in strategy_trades)
            
            avg_win = gross_profit / win_count if win_count > 0 else 0
            avg_loss = gross_loss / loss_count if loss_count > 0 else 0
            
            # Durations
            durations = [t.duration_minutes for t in strategy_trades]
            avg_duration = np.mean(durations) if durations else 0
            
            # Days trading
            unique_days = set(t.exit_time.date() for t in strategy_trades)
            trades_per_day = total / len(unique_days) if unique_days else 0
            
            results[strategy] = StrategyPerformance(
                strategy_name=strategy,
                total_trades=total,
                winning_trades=win_count,
                losing_trades=loss_count,
                win_rate=win_count / total if total > 0 else 0,
                total_pnl=total_pnl,
                avg_win=avg_win,
                avg_loss=avg_loss,
                largest_win=max((t.pnl for t in winners), default=0),
                largest_loss=min((t.pnl for t in losers), default=0),
                profit_factor=gross_profit / gross_loss if gross_loss > 0 else float('inf'),
                expectancy=(win_count/total * avg_win) - (loss_count/total * avg_loss) if total > 0 else 0,
                sharpe_ratio=self._calculate_sharpe_ratio(strategy_trades),
                sortino_ratio=self._calculate_sortino_ratio(strategy_trades),
                max_drawdown=self._calculate_strategy_max_drawdown(strategy_trades),
                avg_trade_duration_minutes=avg_duration,
                trades_per_day=trades_per_day,
                recovery_factor=total_pnl / self._calculate_strategy_max_drawdown(strategy_trades) 
                    if self._calculate_strategy_max_drawdown(strategy_trades) > 0 else 0
            )
        
        return results

    def get_equity_curve_data(self, interval: str = 'trade') -> List[Dict]:
        """
        Get equity curve data for charting.

        Args:
            interval: 'trade', 'hourly', 'daily'

        Returns:
            List of data points for charting
        """
        if interval == 'trade':
            return [
                {
                    'timestamp': p.timestamp.isoformat(),
                    'equity': p.equity,
                    'drawdown': p.drawdown,
                    'drawdown_pct': p.drawdown_pct,
                    'high_water_mark': p.high_water_mark
                }
                for p in self.equity_curve
            ]
        elif interval == 'daily':
            return [
                {
                    'timestamp': dt.isoformat(),
                    'equity': eq
                }
                for dt, eq in self.daily_equity
            ]
        else:
            return []

    def get_trade_distribution(self) -> Dict[str, Any]:
        """Get trade distribution data for charting."""
        pnls = [t.pnl for t in self.trades]
        
        if not pnls:
            return {'histogram': [], 'stats': {}}
        
        # Create histogram bins
        min_pnl = min(pnls)
        max_pnl = max(pnls)
        num_bins = min(20, len(pnls) // 5 + 1)
        
        if num_bins < 2:
            num_bins = 2
        
        bin_width = (max_pnl - min_pnl) / num_bins if max_pnl != min_pnl else 1
        
        histogram = []
        for i in range(num_bins):
            bin_start = min_pnl + (i * bin_width)
            bin_end = bin_start + bin_width
            count = len([p for p in pnls if bin_start <= p < bin_end])
            histogram.append({
                'range': f"${bin_start:.0f} - ${bin_end:.0f}",
                'count': count,
                'bin_start': bin_start,
                'bin_end': bin_end
            })
        
        return {
            'histogram': histogram,
            'stats': {
                'mean': np.mean(pnls),
                'median': np.median(pnls),
                'std': np.std(pnls),
                'skewness': self._calculate_skewness(pnls),
                'kurtosis': self._calculate_kurtosis(pnls),
                'min': min_pnl,
                'max': max_pnl,
                'total': sum(pnls)
            }
        }

    def get_time_analysis(self) -> Dict[str, Any]:
        """Analyze performance by time (hour, day of week, etc.)."""
        if not self.trades:
            return {}
        
        # By hour
        hourly_pnl = {str(h): 0.0 for h in range(24)}
        hourly_count = {str(h): 0 for h in range(24)}
        
        # By day of week
        daily_pnl = {str(d): 0.0 for d in range(7)}  # 0=Monday
        daily_count = {str(d): 0 for d in range(7)}
        
        for trade in self.trades:
            hour = str(trade.entry_time.hour)
            day = str(trade.entry_time.weekday())
            
            hourly_pnl[hour] += trade.pnl
            hourly_count[hour] += 1
            daily_pnl[day] += trade.pnl
            daily_count[day] += 1
        
        return {
            'hourly': {
                'pnl': hourly_pnl,
                'count': hourly_count,
                'avg_pnl': {h: hourly_pnl[h]/hourly_count[h] if hourly_count[h] > 0 else 0 
                           for h in hourly_pnl}
            },
            'daily': {
                'pnl': daily_pnl,
                'count': daily_count,
                'avg_pnl': {d: daily_pnl[d]/daily_count[d] if daily_count[d] > 0 else 0 
                           for d in daily_pnl},
                'labels': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
            }
        }

    # ============================================================
    # HELPER METHODS
    # ============================================================

    def _get_period_start(self, period: MetricPeriod, now: datetime) -> datetime:
        """Get start datetime for a period."""
        if period == MetricPeriod.DAY:
            return now - timedelta(days=1)
        elif period == MetricPeriod.WEEK:
            return now - timedelta(weeks=1)
        elif period == MetricPeriod.MONTH:
            return now - timedelta(days=30)
        elif period == MetricPeriod.QUARTER:
            return now - timedelta(days=90)
        elif period == MetricPeriod.YEAR:
            return now - timedelta(days=365)
        else:  # ALL_TIME
            return datetime.min

    def _get_period_returns(self, start_date: datetime) -> List[float]:
        """Get daily returns for a period."""
        return [
            r for (dt, _), r in zip(self.daily_equity[:-1], self.daily_returns)
            if dt >= start_date
        ]

    def _calculate_sharpe_ratio(self, trades: List[TradeRecord]) -> float:
        """Calculate Sharpe ratio for trades."""
        if len(trades) < 2:
            return 0.0
        
        returns = [t.pnl_percent for t in trades]
        if not returns:
            return 0.0
        
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        
        if std_return == 0:
            return 0.0
        
        # Annualize (assuming ~252 trading days)
        daily_rf = self.risk_free_rate / 252
        return np.sqrt(252) * (mean_return - daily_rf) / std_return

    def _calculate_sortino_ratio(self, trades: List[TradeRecord]) -> float:
        """Calculate Sortino ratio for trades."""
        if len(trades) < 2:
            return 0.0
        
        returns = [t.pnl_percent for t in trades]
        negative_returns = [r for r in returns if r < 0]
        
        if not negative_returns:
            return float('inf') if np.mean(returns) > 0 else 0.0
        
        downside_std = np.std(negative_returns)
        if downside_std == 0:
            return 0.0
        
        daily_rf = self.risk_free_rate / 252
        return np.sqrt(252) * (np.mean(returns) - daily_rf) / downside_std

    def _calculate_max_drawdown(self, period: MetricPeriod) -> Tuple[float, float]:
        """Calculate max drawdown for period."""
        start_date = self._get_period_start(period, datetime.utcnow())
        period_points = [p for p in self.equity_curve if p.timestamp >= start_date]
        
        if not period_points:
            return 0.0, 0.0
        
        max_dd = max(p.drawdown for p in period_points)
        max_dd_pct = max(p.drawdown_pct for p in period_points)
        
        return max_dd, max_dd_pct

    def _calculate_strategy_max_drawdown(self, trades: List[TradeRecord]) -> float:
        """Calculate max drawdown for strategy trades."""
        if not trades:
            return 0.0
        
        equity = self.initial_equity
        peak = equity
        max_dd = 0.0
        
        for trade in sorted(trades, key=lambda t: t.exit_time):
            equity += trade.pnl
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd
        
        return max_dd

    def _calculate_streaks(self, trades: List[TradeRecord]) -> Tuple[int, int]:
        """Calculate winning and losing streaks."""
        if not trades:
            return 0, 0
        
        sorted_trades = sorted(trades, key=lambda t: t.exit_time)
        
        max_win_streak = current_win_streak = 0
        max_loss_streak = current_loss_streak = 0
        
        for trade in sorted_trades:
            if trade.pnl > 0:
                current_win_streak += 1
                current_loss_streak = 0
                max_win_streak = max(max_win_streak, current_win_streak)
            elif trade.pnl < 0:
                current_loss_streak += 1
                current_win_streak = 0
                max_loss_streak = max(max_loss_streak, current_loss_streak)
        
        return max_win_streak, max_loss_streak

    def _group_count_by(self, trades: List[TradeRecord], field: str) -> Dict[str, int]:
        """Group and count trades by field."""
        result = {}
        for trade in trades:
            key = getattr(trade, field, 'unknown')
            result[key] = result.get(key, 0) + 1
        return result

    def _group_pnl_by(self, trades: List[TradeRecord], field: str) -> Dict[str, float]:
        """Group and sum PnL by field."""
        result = {}
        for trade in trades:
            key = getattr(trade, field, 'unknown')
            result[key] = result.get(key, 0.0) + trade.pnl
        return result

    def _calculate_monthly_returns(self, trades: List[TradeRecord]) -> Dict[str, float]:
        """Calculate monthly returns."""
        monthly = {}
        for trade in trades:
            key = trade.exit_time.strftime('%Y-%m')
            monthly[key] = monthly.get(key, 0.0) + trade.pnl
        return monthly

    def _calculate_skewness(self, values: List[float]) -> float:
        """Calculate skewness of distribution."""
        if len(values) < 3:
            return 0.0
        n = len(values)
        mean = np.mean(values)
        std = np.std(values)
        if std == 0:
            return 0.0
        return (n / ((n-1) * (n-2))) * sum(((x - mean) / std) ** 3 for x in values)

    def _calculate_kurtosis(self, values: List[float]) -> float:
        """Calculate kurtosis of distribution."""
        if len(values) < 4:
            return 0.0
        n = len(values)
        mean = np.mean(values)
        std = np.std(values)
        if std == 0:
            return 0.0
        return ((n * (n+1)) / ((n-1) * (n-2) * (n-3))) * \
               sum(((x - mean) / std) ** 4 for x in values) - \
               (3 * (n-1)**2) / ((n-2) * (n-3))

    def get_summary(self) -> Dict[str, Any]:
        """Get quick performance summary."""
        total_trades = len(self.trades)
        winners = len([t for t in self.trades if t.pnl > 0])
        total_pnl = sum(t.pnl for t in self.trades)
        
        return {
            'current_equity': self.current_equity,
            'total_return': self.current_equity - self.initial_equity,
            'total_return_pct': (self.current_equity - self.initial_equity) / self.initial_equity,
            'total_trades': total_trades,
            'win_rate': winners / total_trades if total_trades > 0 else 0,
            'total_pnl': total_pnl,
            'high_water_mark': self.high_water_mark,
            'current_drawdown': self.high_water_mark - self.current_equity,
            'current_drawdown_pct': (self.high_water_mark - self.current_equity) / self.high_water_mark if self.high_water_mark > 0 else 0,
        }
