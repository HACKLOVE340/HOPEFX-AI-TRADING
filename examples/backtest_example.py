#!/usr/bin/env python3
"""
HOPEFX Backtest Example - WORKING PROTOTYPE
Runs a simple moving average crossover backtest on synthetic XAUUSD data.
Generates equity curve and metrics.
"""

import json
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any

import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('backtest')


class XAUUSDDataGenerator:
    """Generate realistic synthetic XAUUSD OHLCV data for testing."""
    
    def __init__(self, start_date='2024-01-01', days=90):
        self.start_date = datetime.strptime(start_date, '%Y-%m-%d')
        self.days = days
        self.base_price = 2000.0
        
    def generate(self) -> List[Dict]:
        """Generate synthetic tick data."""
        data = []
        price = self.base_price
        
        for day in range(self.days):
            date = self.start_date + timedelta(days=day)
            
            # Skip weekends
            if date.weekday() >= 5:
                continue
                
            # Generate 24 hourly candles per day
            for hour in range(24):
                # Random walk with slight upward drift
                change = random.gauss(0.1, 1.5)
                price = max(1800, min(2200, price + change))
                
                # Generate OHLC from price
                volatility = abs(random.gauss(0, 0.5))
                open_p = price - random.gauss(0, 0.2)
                high_p = max(open_p, price) + volatility * 0.5
                low_p = min(open_p, price) - volatility * 0.5
                close_p = price
                volume = random.randint(1000, 10000)
                
                data.append({
                    'timestamp': date.replace(hour=hour).isoformat(),
                    'open': round(open_p, 2),
                    'high': round(high_p, 2),
                    'low': round(low_p, 2),
                    'close': round(close_p, 2),
                    'volume': volume
                })
        
        return data


class MovingAverageCrossover:
    """Simple MA Crossover strategy."""
    
    def __init__(self, fast_period=10, slow_period=30):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.prices = []
        self.position = None  # None, 'long', 'short'
        
    def on_data(self, candle: Dict) -> str:
        """Process new candle and return signal."""
        self.prices.append(candle['close'])
        
        if len(self.prices) < self.slow_period:
            return 'hold'
        
        fast_ma = np.mean(self.prices[-self.fast_period:])
        slow_ma = np.mean(self.prices[-self.slow_period:])
        
        # Crossover logic
        prev_fast = np.mean(self.prices[-self.fast_period-1:-1])
        prev_slow = np.mean(self.prices[-self.slow_period-1:-1])
        
        if prev_fast <= prev_slow and fast_ma > slow_ma:
            return 'buy'
        elif prev_fast >= prev_slow and fast_ma < slow_ma:
            return 'sell'
        
        return 'hold'


class BacktestEngine:
    """Simple backtesting engine."""
    
    def __init__(self, data: List[Dict], strategy, initial_capital=10000.0):
        self.data = data
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.equity_curve = []
        self.trades = []
        self.position = None
        self.commission = 0.001  # 0.1%
        self.slippage = 0.05   # $0.05 slippage for XAUUSD
        
    def run(self) -> Dict:
        """Run backtest and return results."""
        logger.info("Starting backtest...")
        
        for i, candle in enumerate(self.data):
            signal = self.strategy.on_data(candle)
            
            # Execute signals
            if signal == 'buy' and self.position is None:
                self._enter_position(candle, 'long')
            elif signal == 'sell' and self.position is not None:
                self._exit_position(candle)
            
            # Track equity
            equity = self._calculate_equity(candle)
            self.equity_curve.append({
                'timestamp': candle['timestamp'],
                'equity': equity,
                'price': candle['close']
            })
        
        # Close any open position at end
        if self.position is not None:
            self._exit_position(self.data[-1])
        
        return self._calculate_metrics()
    
    def _enter_position(self, candle: Dict, side: str):
        """Enter a position."""
        entry_price = candle['close'] + self.slippage
        qty = (self.capital * 0.95) / entry_price  # Use 95% of capital
        
        self.position = {
            'side': side,
            'entry_price': entry_price,
            'qty': qty,
            'entry_time': candle['timestamp']
        }
        
        commission_cost = entry_price * qty * self.commission
        self.capital -= commission_cost
        
        logger.info(f"ENTER LONG: {qty:.4f} @ {entry_price:.2f}")
    
    def _exit_position(self, candle: Dict):
        """Exit current position."""
        if self.position is None:
            return
            
        exit_price = candle['close'] - self.slippage
        qty = self.position['qty']
        entry_price = self.position['entry_price']
        
        # Calculate P&L
        gross_pnl = (exit_price - entry_price) * qty
        commission_cost = (entry_price + exit_price) * qty * self.commission
        net_pnl = gross_pnl - commission_cost
        
        # Update capital
        self.capital += (exit_price * qty) - commission_cost
        
        trade = {
            'entry_time': self.position['entry_time'],
            'exit_time': candle['timestamp'],
            'entry_price': entry_price,
            'exit_price': exit_price,
            'qty': qty,
            'gross_pnl': gross_pnl,
            'commission': commission_cost,
            'net_pnl': net_pnl,
            'return_pct': (net_pnl / (entry_price * qty)) * 100
        }
        self.trades.append(trade)
        
        logger.info(f"EXIT: @ {exit_price:.2f} | P&L: ${net_pnl:.2f}")
        self.position = None
    
    def _calculate_equity(self, candle: Dict) -> float:
        """Calculate current equity."""
        if self.position is None:
            return self.capital
        
        current_value = self.position['qty'] * candle['close']
        return self.capital + current_value
    
    def _calculate_metrics(self) -> Dict:
        """Calculate performance metrics."""
        if not self.trades:
            return {'error': 'No trades executed'}
        
        returns = [t['net_pnl'] for t in self.trades]
        win_trades = [r for r in returns if r > 0]
        loss_trades = [r for r in returns if r <= 0]
        
        equity_values = [e['equity'] for e in self.equity_curve]
        
        # Calculate max drawdown
        peak = self.initial_capital
        max_dd = 0
        for equity in equity_values:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd
        
        # Calculate Sharpe (simplified, assuming 252 trading days)
        if len(equity_values) > 1:
            daily_returns = np.diff(equity_values) / equity_values[:-1]
            sharpe = np.mean(daily_returns) / (np.std(daily_returns) + 1e-10) * np.sqrt(252)
        else:
            sharpe = 0
        
        total_return = (self.capital - self.initial_capital) / self.initial_capital
        
        metrics = {
            'initial_capital': self.initial_capital,
            'final_capital': self.capital,
            'total_return_pct': total_return * 100,
            'total_trades': len(self.trades),
            'winning_trades': len(win_trades),
            'losing_trades': len(loss_trades),
            'win_rate_pct': (len(win_trades) / len(self.trades) * 100) if self.trades else 0,
            'avg_win': np.mean(win_trades) if win_trades else 0,
            'avg_loss': np.mean(loss_trades) if loss_trades else 0,
            'profit_factor': abs(sum(win_trades) / sum(loss_trades)) if loss_trades and sum(loss_trades) != 0 else float('inf'),
            'max_drawdown_pct': max_dd * 100,
            'sharpe_ratio': sharpe,
            'total_commission': sum(t['commission'] for t in self.trades),
            'gross_profit': sum(win_trades),
            'gross_loss': sum(loss_trades),
            'net_profit': sum(returns)
        }
        
        return metrics
    
    def save_equity_curve(self, filename: str):
        """Save equity curve to JSON."""
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        with open(filename, 'w') as f:
            json.dump(self.equity_curve, f, indent=2)
        logger.info(f"Equity curve saved to: {filename}")


def main():
    """Run backtest example."""
    print("=" * 60)
    print("HOPEFX Backtest Example")
    print("Strategy: Moving Average Crossover on XAUUSD")
    print("=" * 60)
    
    # Generate data
    logger.info("Generating synthetic XAUUSD data...")
    data_gen = XAUUSDDataGenerator(start_date='2024-01-01', days=90)
    data = data_gen.generate()
    logger.info(f"Generated {len(data)} candles")
    
    # Create strategy
    strategy = MovingAverageCrossover(fast_period=10, slow_period=30)
    
    # Run backtest
    engine = BacktestEngine(data, strategy, initial_capital=10000.0)
    metrics = engine.run()
    
    # Print results
    print("\\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    print(f"Initial Capital: ${metrics['initial_capital']:.2f}")
    print(f"Final Capital:   ${metrics['final_capital']:.2f}")
    print(f"Total Return:    {metrics['total_return_pct']:.2f}%")
    print(f"Total Trades:    {metrics['total_trades']}")
    print(f"Win Rate:        {metrics['win_rate_pct']:.1f}%")
    print(f"Profit Factor:   {metrics['profit_factor']:.2f}")
    print(f"Max Drawdown:    {metrics['max_drawdown_pct']:.2f}%")
    print(f"Sharpe Ratio:    {metrics['sharpe_ratio']:.2f}")
    print(f"Total Commission: ${metrics['total_commission']:.2f}")
    print("=" * 60)
    
    # Save results
    results_dir = Path('results')
    results_dir.mkdir(exist_ok=True)
    
    # Save metrics
    metrics_file = results_dir / 'backtest_metrics.json'
    with open(metrics_file, 'w') as f:
        json.dump(metrics, f, indent=2)
    print(f"\\nMetrics saved to: {metrics_file}")
    
    # Save equity curve
    engine.save_equity_curve(results_dir / 'equity_curve.json')
    
    # Generate plot if matplotlib available
    try:
        import matplotlib.pyplot as plt
        
        fig, axes = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [3, 1]})
        
        # Equity curve
        timestamps = [e['timestamp'][:10] for e in engine.equity_curve[::24]]  # Daily samples
        equities = [e['equity'] for e in engine.equity_curve[::24]]
        
        axes[0].plot(range(len(equities)), equities, label='Equity', color='#2E86AB', linewidth=2)
        axes[0].axhline(y=metrics['initial_capital'], color='gray', linestyle='--', alpha=0.5)
        axes[0].set_title('XAUUSD MA Crossover Backtest - Equity Curve', fontsize=14, fontweight='bold')
        axes[0].set_ylabel('Equity ($)')
        axes[0].legend()
        axes[0].grid(True, alpha=0.3)
        
        # Drawdown
        peak = metrics['initial_capital']
        drawdowns = []
        for equity in [e['equity'] for e in engine.equity_curve[::24]]:
            if equity > peak:
                peak = equity
            drawdowns.append((peak - equity) / peak * 100)
        
        axes[1].fill_between(range(len(drawdowns)), drawdowns, color='#E94F37', alpha=0.3)
        axes[1].plot(range(len(drawdowns)), drawdowns, color='#E94F37', linewidth=1)
        axes[1].set_title('Drawdown %', fontsize=12)
        axes[1].set_ylabel('Drawdown (%)')
        axes[1].set_xlabel('Trading Days')
        axes[1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        plot_file = results_dir / 'equity_curve.png'
        plt.savefig(plot_file, dpi=150, bbox_inches='tight')
        print(f"Plot saved to: {plot_file}")
        plt.close()
        
    except ImportError:
        logger.warning("matplotlib not installed, skipping plot generation")
        print("Install matplotlib to generate equity curve plots: pip install matplotlib")
    
    print("\\n✅ Backtest complete!")
    return metrics


if __name__ == '__main__':
    results = main()
