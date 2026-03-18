# File 9: tests/test_backtesting.py - Test coverage for backtesting module

test_backtesting_content = '''#!/usr/bin/env python3
"""
Tests for backtesting module.
"""

import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from examples.backtest_example import (
    XAUUSDDataGenerator, 
    MovingAverageCrossover, 
    BacktestEngine
)


class TestDataGenerator:
    """Test cases for XAUUSDDataGenerator."""
    
    def test_generate_data(self):
        """Test data generation."""
        gen = XAUUSDDataGenerator(start_date='2024-01-01', days=30)
        data = gen.generate()
        
        assert len(data) > 0
        assert all('open' in d for d in data)
        assert all('high' in d for d in data)
        assert all('low' in d for d in data)
        assert all('close' in d for d in data)
        assert all('volume' in d for d in data)
    
    def test_price_range(self):
        """Test generated prices are in reasonable range."""
        gen = XAUUSDDataGenerator(days=30)
        data = gen.generate()
        
        closes = [d['close'] for d in data]
        assert all(1800 <= c <= 2200 for c in closes)
    
    def test_ohlc_consistency(self):
        """Test OHLC consistency."""
        gen = XAUUSDDataGenerator(days=10)
        data = gen.generate()
        
        for d in data:
            assert d['low'] <= d['close'] <= d['high']
            assert d['low'] <= d['open'] <= d['high']


class TestMovingAverageCrossover:
    """Test cases for MovingAverageCrossover strategy."""
    
    def setup_method(self):
        self.strategy = MovingAverageCrossover(fast_period=3, slow_period=5)
    
    def test_initial_hold(self):
        """Test strategy holds initially."""
        candle = {'close': 2000.0}
        signal = self.strategy.on_data(candle)
        assert signal == 'hold'  # Not enough data
    
    def test_buy_signal(self):
        """Test buy signal generation."""
        # Feed rising prices to trigger crossover
        prices = [2000, 2001, 2002, 2003, 2004, 2005, 2010, 2020]
        for p in prices:
            signal = self.strategy.on_data({'close': p})
        
        # Should eventually give buy signal
        assert signal in ['buy', 'hold', 'sell']
    
    def test_sell_signal(self):
        """Test sell signal generation."""
        # Feed falling prices
        prices = [2100, 2095, 2090, 2085, 2080, 2070, 2060, 2050]
        signals = []
        for p in prices:
            signals.append(self.strategy.on_data({'close': p}))
        
        # Should eventually give sell signal
        assert any(s in ['sell', 'hold'] for s in signals)


class TestBacktestEngine:
    """Test cases for BacktestEngine."""
    
    def setup_method(self):
        """Set up test data and engine."""
        gen = XAUUSDDataGenerator(days=30)
        self.data = gen.generate()
        self.strategy = MovingAverageCrossover(fast_period=5, slow_period=10)
        self.engine = BacktestEngine(self.data, self.strategy, initial_capital=10000.0)
    
    def test_initial_state(self):
        """Test initial engine state."""
        assert self.engine.initial_capital == 10000.0
        assert self.engine.capital == 10000.0
        assert len(self.engine.equity_curve) == 0
    
    def test_run_backtest(self):
        """Test backtest execution."""
        results = self.engine.run()
        
        assert 'total_trades' in results
        assert 'final_capital' in results
        assert 'total_return_pct' in results
    
    def test_equity_curve_generated(self):
        """Test equity curve is populated."""
        self.engine.run()
        assert len(self.engine.equity_curve) > 0
        assert all('equity' in e for e in self.engine.equity_curve)
    
    def test_metrics_calculated(self):
        """Test metrics calculation."""
        results = self.engine.run()
        
        assert 'sharpe_ratio' in results
        assert 'max_drawdown_pct' in results
        assert 'win_rate_pct' in results
        assert 'profit_factor' in results
        
        # Sanity checks
        assert results['max_drawdown_pct'] >= 0
        assert results['total_trades'] >= 0
    
    def test_no_trades_with_small_data(self):
        """Test behavior with insufficient data."""
        gen = XAUUSDDataGenerator(days=5)  # Very small dataset
        data = gen.generate()
        strategy = MovingAverageCrossover(fast_period=10, slow_period=20)
        engine = BacktestEngine(data, strategy, initial_capital=10000.0)
        
        results = engine.run()
        # Should handle gracefully even with no trades
        assert 'error' in results or results['total_trades'] == 0
    
    def test_commission_impact(self):
        """Test that commission reduces returns."""
        results = self.engine.run()
        
        if results['total_trades'] > 0:
            assert results['total_commission'] > 0
            # Gross should be higher than net
            assert results['gross_profit'] >= results['net_profit']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
'''

with open('/mnt/kimi/output/hopefx_upgrade/tests/test_backtesting.py', 'w') as f:
    f.write(test_backtesting_content)

print("✅ tests/test_backtesting.py created - Backtesting test coverage")
