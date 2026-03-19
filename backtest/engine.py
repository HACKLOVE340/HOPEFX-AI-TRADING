"""
HOPEFX Backtesting Engine
Event-driven backtesting with realistic execution simulation
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import json

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """Backtest configuration"""
    start_date: datetime
    end_date: datetime
    symbols: List[str]
    initial_capital: float = 100000.0
    commission_per_trade: float = 5.0  # Dollars
    slippage_model: str = "fixed"  # fixed, variable, none
    slippage_pips: float = 0.5
    allow_short: bool = True
    max_positions: int = 10


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
    sharpe_ratio: float
    equity_curve: List[Dict]
    trades: List[Dict]
    metrics: Dict[str, float]


class HistoricalDataLoader:
    """Load historical data for backtesting"""
    
    def __init__(self, data_source: str = "database"):
        self.data_source = data_source
        self._cache: Dict[str, pd.DataFrame] = {}
    
    async def load_data(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime
    ) -> Optional[pd.DataFrame]:
        """Load historical OHLCV data"""
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
                                'symbol': symbol,
                                'timeframe': timeframe,
                                'start': start,
                                'end': end
                            }
                        )
                        
                        self._cache[cache_key] = df
                        return df
            
            # Fallback: generate synthetic data for testing
            logger.warning(f"Using synthetic data for {symbol}")
            return self._generate_synthetic_data(symbol, start, end)
            
        except Exception as e:
            logger.error(f"Failed to load data for {symbol}: {e}")
            return None
    
    def _generate_synthetic_data(
        self,
        symbol: str,
        start: datetime,
        end: datetime
    ) -> pd.DataFrame:
        """Generate synthetic price data for testing"""
        periods = int((end - start).total_seconds() / 3600)  # Hourly bars
        
        np.random.seed(42)  # Reproducible
        
        # Generate random walk
        returns = np.random.normal(0.0001, 0.001, periods)
        prices = 100 * np.exp(np.cumsum(returns))
        
        # Generate OHLC from close
        df = pd.DataFrame({
            'timestamp': pd.date_range(start, periods=periods, freq='H'),
            'close': prices
        })
        
        df['open'] = df['close'].shift(1)
        df['high'] = df[['open', 'close']].max(axis=1) * (1 + abs(np.random.normal(0, 0.001, periods)))
        df['low'] = df[['open', 'close']].min(axis=1) * (1 - abs(np.random.normal(0, 0.001, periods)))
        df['volume'] = np.random.randint(1000, 10000, periods)
        
        df = df.fillna(method='bfill')
        
        return df


class SimulatedBroker:
    """Broker simulation for backtesting"""
    
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.cash = config.initial_capital
        self.positions: Dict[str, Dict] = {}
        self.trades: List[Dict] = []
        self.equity_curve: List[Dict] = []
        self.current_time: Optional[datetime] = None
    
    def update_time(self, timestamp: datetime):
        """Update current simulation time"""
        self.current_time = timestamp
        
        # Record equity
        equity = self.get_equity()
        self.equity_curve.append({
            'timestamp': timestamp.isoformat(),
            'equity': equity,
            'cash': self.cash,
            'positions_value': equity - self.cash
        })
    
    def get_equity(self) -> float:
        """Calculate total equity"""
        positions_value = sum(
            pos['quantity'] * pos['current_price']
            for pos in self.positions.values()
        )
        return self.cash + positions_value
    
    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        current_price: float
    ) -> Dict:
        """Simulate market order execution"""
        # Apply slippage
        slippage = self._calculate_slippage(current_price)
        
        if side == 'buy':
            fill_price = current_price * (1 + slippage)
        else:
            fill_price = current_price * (1 - slippage)
        
        # Calculate cost
        cost = quantity * fill_price
        commission = self.config.commission_per_trade
        
        # Check funds
        if side == 'buy' and cost + commission > self.cash:
            return {
                'success': False,
                'error': 'Insufficient funds'
            }
        
        # Execute
        if side == 'buy':
            self.cash -= (cost + commission)
            
            if symbol in self.positions:
                # Add to existing position
                pos = self.positions[symbol]
                total_qty = pos['quantity'] + quantity
                avg_price = (pos['avg_price'] * pos['quantity'] + fill_price * quantity) / total_qty
                pos['quantity'] = total_qty
                pos['avg_price'] = avg_price
            else:
                # New position
                self.positions[symbol] = {
                    'quantity': quantity,
                    'avg_price': fill_price,
                    'current_price': current_price,
                    'side': 'long'
                }
        else:
            # Sell
                       self.cash += (cost - commission)
            
            if symbol in self.positions:
                pos = self.positions[symbol]
                if pos['quantity'] <= quantity:
                    # Close position
                    realized_pnl = (fill_price - pos['avg_price']) * pos['quantity']
                    if pos['side'] == 'short':
                        realized_pnl = -realized_pnl
                    
                    self._record_trade(symbol, 'close', pos['quantity'], 
                                     pos['avg_price'], fill_price, realized_pnl, commission)
                    del self.positions[symbol]
                else:
                    # Partial close
                    pos['quantity'] -= quantity
            else:
                # Short sell
                self.positions[symbol] = {
                    'quantity': quantity,
                    'avg_price': fill_price,
                    'current_price': current_price,
                    'side': 'short'
                }
        
        return {
            'success': True,
            'fill_price': fill_price,
            'quantity': quantity,
            'commission': commission
        }
    
    def _calculate_slippage(self, price: float) -> float:
        """Calculate execution slippage"""
        if self.config.slippage_model == 'none':
            return 0.0
        
        if self.config.slippage_model == 'fixed':
            # Fixed pips slippage
            pip = 0.0001 if 'JPY' not in str(price) else 0.01
            return (self.config.slippage_pips * pip) / price
        
        # Variable slippage based on volatility
        return np.random.normal(0, self.config.slippage_pips * 0.0001)
    
    def _record_trade(self, symbol: str, action: str, quantity: float,
                     entry_price: float, exit_price: float, 
                     pnl: float, commission: float):
        """Record completed trade"""
        self.trades.append({
            'timestamp': self.current_time.isoformat() if self.current_time else None,
            'symbol': symbol,
            'action': action,
            'quantity': quantity,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl': pnl,
            'commission': commission,
            'net_pnl': pnl - commission
        })
    
    def update_prices(self, prices: Dict[str, float]):
        """Update position prices for P&L calculation"""
        for symbol, price in prices.items():
            if symbol in self.positions:
                self.positions[symbol]['current_price'] = price


class BacktestEngine:
    """
    Event-driven backtesting engine
    
    Features:
    - Realistic execution simulation
    - Multiple strategy support
    - Performance analytics
    - Walk-forward analysis ready
    """
    
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.data_loader = HistoricalDataLoader()
        self.broker = SimulatedBroker(config)
        self.strategies: List[Any] = []
        self.results: Optional[BacktestResult] = None
        
        # Event log
        self.events: List[Dict] = []
    
    def add_strategy(self, strategy: Any):
        """Add strategy to backtest"""
        self.strategies.append(strategy)
    
    async def run(self, progress_callback: Optional[Callable] = None) -> BacktestResult:
        """
        Run backtest
        
        Args:
            progress_callback: Called with (current_step, total_steps, current_time)
        """
        logger.info(f"Starting backtest: {self.config.start_date} to {self.config.end_date}")
        
        # Load data for all symbols
        all_data: Dict[str, pd.DataFrame] = {}
        for symbol in self.config.symbols:
            df = await self.data_loader.load_data(
                symbol, '1h', 
                self.config.start_date, 
                self.config.end_date
            )
            if df is not None:
                all_data[symbol] = df
                logger.info(f"Loaded {len(df)} bars for {symbol}")
        
        if not all_data:
            raise ValueError("No data loaded for backtest")
        
        # Combine timestamps
        all_timestamps = sorted(set(
            ts for df in all_data.values() 
            for ts in df['timestamp']
        ))
        
        total_steps = len(all_timestamps)
        
        # Main backtest loop
        for i, timestamp in enumerate(all_timestamps):
            self.broker.update_time(timestamp)
            
            # Build current price snapshot
            current_prices = {}
            for symbol, df in all_data.items():
                # Find price at or before timestamp
                mask = df['timestamp'] <= timestamp
                if mask.any():
                    row = df[mask].iloc[-1]
                    current_prices[symbol] = row['close']
            
            # Update broker prices
            self.broker.update_prices(current_prices)
            
            # Generate signals from strategies
            for strategy in self.strategies:
                try:
                    signals = strategy.generate_signals(
                        timestamp=timestamp,
                        prices=current_prices,
                        data=all_data
                    )
                    
                    for signal in signals:
                        self._process_signal(signal, timestamp, current_prices)
                        
                except Exception as e:
                    logger.error(f"Strategy error at {timestamp}: {e}")
            
            # Progress callback
            if progress_callback and i % 100 == 0:
                progress_callback(i, total_steps, timestamp)
        
        # Calculate results
        self.results = self._calculate_results()
        
        logger.info(f"Backtest complete: {self.results.total_trades} trades")
        
        return self.results
    
    def _process_signal(self, signal: Dict, timestamp: datetime, prices: Dict[str, float]):
        """Process trading signal"""
        symbol = signal.get('symbol')
        action = signal.get('action')
        
        if symbol not in prices:
            return
        
        current_price = prices[symbol]
        quantity = signal.get('size', 1000)  # Default size
        
        # Execute through simulated broker
        result = self.broker.place_market_order(symbol, action, quantity, current_price)
        
        if result['success']:
            self.events.append({
                'timestamp': timestamp.isoformat(),
                'type': 'order_filled',
                'symbol': symbol,
                'action': action,
                'price': result['fill_price'],
                'quantity': quantity
            })
    
    def _calculate_results(self) -> BacktestResult:
        """Calculate performance metrics"""
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
                metrics={}
            )
        
        # Basic stats
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t['net_pnl'] > 0)
        losing_trades = total_trades - winning_trades
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        # P&L
        total_pnl = sum(t['net_pnl'] for t in trades)
        gross_profit = sum(t['net_pnl'] for t in trades if t['net_pnl'] > 0)
        gross_loss = sum(t['net_pnl'] for t in trades if t['net_pnl'] < 0)
        profit_factor = abs(gross_profit / gross_loss) if gross_loss != 0 else float('inf')
        
        # Returns
        initial_equity = self.config.initial_capital
        final_equity = self.broker.get_equity()
        total_return = (final_equity - initial_equity) / initial_equity
        
        # Drawdown
        equity_values = [e['equity'] for e in self.broker.equity_curve]
        peak = initial_equity
        max_drawdown = 0
        
        for equity in equity_values:
            if equity > peak:
                peak = equity
            drawdown = (peak - equity) / peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        # Sharpe ratio (simplified)
        if len(equity_values) > 1:
            returns = np.diff(equity_values) / equity_values[:-1]
            if len(returns) > 0 and np.std(returns) > 0:
                sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252 * 24)  # Hourly to annual
            else:
                sharpe = 0
        else:
            sharpe = 0
        
        # Additional metrics
        metrics = {
            'avg_trade_pnl': total_pnl / total_trades,
            'avg_winning_trade': gross_profit / winning_trades if winning_trades > 0 else 0,
            'avg_losing_trade': gross_loss / losing_trades if losing_trades > 0 else 0,
            'max_consecutive_wins': self._max_consecutive(trades, 'win'),
            'max_consecutive_losses': self._max_consecutive(trades, 'loss'),
            'recovery_factor': total_return / max_drawdown if max_drawdown > 0 else 0
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
            equity_curve=self.broker.equity_curve,
            trades=trades,
            metrics=metrics
        )
    
    def _max_consecutive(self, trades: List[Dict], trade_type: str) -> int:
        """Calculate max consecutive wins or losses"""
        max_streak = 0
        current_streak = 0
        
        for trade in trades:
            is_win = trade['net_pnl'] > 0
            
            if (trade_type == 'win' and is_win) or (trade_type == 'loss' and not is_win):
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
        
        report = f"""
╔════════════════════════════════════════════════════════════════╗
║                    HOPEFX BACKTEST REPORT                       ║
╠════════════════════════════════════════════════════════════════╣
║ Period:     {self.config.start_date.strftime('%Y-%m-%d')} to {self.config.end_date.strftime('%Y-%m-%d')}          ║
║ Symbols:    {', '.join(self.config.symbols)}                          ║
║ Initial:    ${self.config.initial_capital:,.2f}                                  ║
╠════════════════════════════════════════════════════════════════╣
║ PERFORMANCE                                                    ║
║   Total Return:      {r.total_return*100:>10.2f}%                            ║
║   Final Equity:      ${r.equity_curve[-1]['equity'] if r.equity_curve else 0:>10,.2f}                          ║
║   Sharpe Ratio:      {r.sharpe_ratio:>10.2f}                            ║
║   Max Drawdown:      {r.max_drawdown*100:>10.2f}%                            ║
╠════════════════════════════════════════════════════════════════╣
║ TRADE STATISTICS                                               ║
║   Total Trades:      {r.total_trades:>10}                             ║
║   Win Rate:          {r.win_rate*100:>10.1f}%                            ║
║   Profit Factor:      {r.profit_factor:>10.2f}                            ║
║   Avg Trade P&L:     ${r.metrics.get('avg_trade_pnl', 0):>10.2f}                          ║
╠════════════════════════════════════════════════════════════════╣
║ Advanced Metrics                                               ║
║   Recovery Factor:   {r.metrics.get('recovery_factor', 0):>10.2f}                            ║
║   Max Consec Wins:   {r.metrics.get('max_consecutive_wins', 0):>10}                             ║
║   Max Consec Losses: {r.metrics.get('max_consecutive_losses', 0):>10}                             ║
╚════════════════════════════════════════════════════════════════╝
        """
        
        return report
    
    def export_to_json(self, filepath: str):
        """Export results to JSON"""
        if not self.results:
            raise ValueError("No results to export")
        
        data = {
            'config': {
                'start_date': self.config.start_date.isoformat(),
                'end_date': self.config.end_date.isoformat(),
                'symbols': self.config.symbols,
                'initial_capital': self.config.initial_capital
            },
            'results': {
                'total_return': self.results.total_return,
                'total_trades': self.results.total_trades,
                'win_rate': self.results.win_rate,
                'profit_factor': self.results.profit_factor,
                'max_drawdown': self.results.max_drawdown,
                'sharpe_ratio': self.results.sharpe_ratio,
                'metrics': self.results.metrics
            },
            'equity_curve': self.results.equity_curve,
            'trades': self.results.trades
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        logger.info(f"Backtest results exported to {filepath}")


# Convenience functions
async def run_backtest(
    strategy: Any,
    symbols: List[str],
    start_date: datetime,
    end_date: datetime,
    initial_capital: float = 100000.0
) -> BacktestResult:
    """Quick backtest function"""
    config = BacktestConfig(
        start_date=start_date,
        end_date=end_date,
        symbols=symbols,
        initial_capital=initial_capital
    )
    
    engine = BacktestEngine(config)
    engine.add_strategy(strategy)
    
    return await engine.run()

