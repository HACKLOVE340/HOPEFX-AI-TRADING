"""
Tests for the backtesting module.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from backtesting.portfolio import Portfolio
from backtesting.events import FillEvent, EventType
from backtesting.metrics import PerformanceMetrics


class TestPortfolio:
    """Tests for Portfolio class."""
    
    def test_portfolio_initialization(self):
        """Test portfolio initialization with default capital."""
        portfolio = Portfolio()
        
        assert portfolio.initial_capital == 100000.0
        assert portfolio.cash == 100000.0
        assert portfolio.equity == 100000.0
        assert len(portfolio.positions) == 0
        assert len(portfolio.trade_history) == 0
    
    def test_portfolio_custom_capital(self):
        """Test portfolio initialization with custom capital."""
        portfolio = Portfolio(initial_capital=50000.0)
        
        assert portfolio.initial_capital == 50000.0
        assert portfolio.cash == 50000.0
        assert portfolio.equity == 50000.0
    
    def test_portfolio_empty_equity_curve(self):
        """Test that initial portfolio has empty equity curve."""
        portfolio = Portfolio()
        
        assert len(portfolio.equity_curve) == 0
        assert portfolio.total_trades == 0
        assert portfolio.winning_trades == 0
        assert portfolio.losing_trades == 0
    
    def test_get_equity_dataframe_empty(self):
        """Test getting equity dataframe from empty portfolio."""
        portfolio = Portfolio()
        
        df = portfolio.get_equity_curve()
        
        assert isinstance(df, pd.DataFrame)
        # Empty portfolio should have no data
        assert len(df) == 0
    
    def test_get_trade_history(self):
        """Test getting trade history from empty portfolio."""
        portfolio = Portfolio()
        
        # Trade history is a list
        assert isinstance(portfolio.trade_history, list)
        assert len(portfolio.trade_history) == 0


class TestPerformanceMetrics:
    """Tests for PerformanceMetrics class."""
    
    @pytest.fixture
    def sample_equity_curve(self):
        """Create sample equity curve data."""
        # Use fixed seed for reproducible tests
        np.random.seed(42)
        dates = pd.date_range(start='2024-01-01', periods=30, freq='D')
        equity_values = [100000 + i * 100 + np.random.randn() * 50 for i in range(30)]
        
        df = pd.DataFrame({
            'equity': equity_values
        }, index=dates)
        
        return df
    
    @pytest.fixture
    def sample_trade_history(self):
        """Create sample trade history."""
        # Use fixed datetime values for reproducible tests
        base_time = datetime(2024, 1, 15, 10, 0, 0)
        trades = [
            {'symbol': 'EUR/USD', 'pnl': 150.0, 'entry_time': base_time, 'exit_time': base_time + timedelta(hours=2)},
            {'symbol': 'EUR/USD', 'pnl': -50.0, 'entry_time': base_time, 'exit_time': base_time + timedelta(hours=1)},
            {'symbol': 'GBP/USD', 'pnl': 200.0, 'entry_time': base_time, 'exit_time': base_time + timedelta(hours=3)},
            {'symbol': 'USD/JPY', 'pnl': -100.0, 'entry_time': base_time, 'exit_time': base_time + timedelta(minutes=30)},
            {'symbol': 'EUR/USD', 'pnl': 75.0, 'entry_time': base_time, 'exit_time': base_time + timedelta(hours=4)},
        ]
        return pd.DataFrame(trades)
    
    def test_metrics_initialization(self, sample_equity_curve, sample_trade_history):
        """Test metrics calculator initialization."""
        metrics = PerformanceMetrics(
            equity_curve=sample_equity_curve,
            trade_history=sample_trade_history,
            initial_capital=100000.0
        )
        
        assert metrics.initial_capital == 100000.0
        assert metrics.risk_free_rate == 0.02
        assert len(metrics.equity_curve) == 30
        assert len(metrics.trade_history) == 5
    
    def test_calculate_total_return(self, sample_equity_curve, sample_trade_history):
        """Test total return calculation."""
        metrics = PerformanceMetrics(
            equity_curve=sample_equity_curve,
            trade_history=sample_trade_history,
            initial_capital=100000.0
        )
        
        total_return = metrics.calculate_total_return()
        
        assert isinstance(total_return, float)
        # Return is percentage
    
    def test_calculate_total_return_empty(self):
        """Test total return with empty equity curve."""
        metrics = PerformanceMetrics(
            equity_curve=pd.DataFrame(),
            trade_history=pd.DataFrame(),
            initial_capital=100000.0
        )
        
        total_return = metrics.calculate_total_return()
        
        assert total_return == 0.0
    
    def test_calculate_max_drawdown(self, sample_equity_curve, sample_trade_history):
        """Test max drawdown calculation."""
        metrics = PerformanceMetrics(
            equity_curve=sample_equity_curve,
            trade_history=sample_trade_history,
            initial_capital=100000.0
        )
        
        max_dd = metrics.calculate_max_drawdown()
        
        assert isinstance(max_dd, float)
        # Drawdown should be 0 or negative percentage
        assert max_dd <= 0
    
    def test_calculate_sharpe_ratio(self, sample_equity_curve, sample_trade_history):
        """Test Sharpe ratio calculation."""
        metrics = PerformanceMetrics(
            equity_curve=sample_equity_curve,
            trade_history=sample_trade_history,
            initial_capital=100000.0
        )
        
        sharpe = metrics.calculate_sharpe_ratio()
        
        assert isinstance(sharpe, float)
    
    def test_calculate_win_rate(self, sample_equity_curve, sample_trade_history):
        """Test win rate calculation."""
        metrics = PerformanceMetrics(
            equity_curve=sample_equity_curve,
            trade_history=sample_trade_history,
            initial_capital=100000.0
        )
        
        win_rate = metrics.calculate_win_rate()
        
        assert isinstance(win_rate, float)
        assert 0 <= win_rate <= 100  # Win rate is percentage
    
    def test_calculate_win_rate_empty(self):
        """Test win rate with no trades."""
        metrics = PerformanceMetrics(
            equity_curve=pd.DataFrame(),
            trade_history=pd.DataFrame(),
            initial_capital=100000.0
        )
        
        win_rate = metrics.calculate_win_rate()
        
        assert win_rate == 0.0
    
    def test_calculate_total_trades(self, sample_equity_curve, sample_trade_history):
        """Test total trades count."""
        metrics = PerformanceMetrics(
            equity_curve=sample_equity_curve,
            trade_history=sample_trade_history,
            initial_capital=100000.0
        )
        
        total = metrics.calculate_total_trades()
        
        assert total == 5
    
    def test_calculate_all_metrics(self, sample_equity_curve, sample_trade_history):
        """Test calculating all metrics at once."""
        metrics = PerformanceMetrics(
            equity_curve=sample_equity_curve,
            trade_history=sample_trade_history,
            initial_capital=100000.0
        )
        
        all_metrics = metrics.calculate_all_metrics()
        
        assert isinstance(all_metrics, dict)
        assert 'total_return' in all_metrics
        assert 'sharpe_ratio' in all_metrics
        assert 'max_drawdown' in all_metrics
        assert 'win_rate' in all_metrics
        assert 'total_trades' in all_metrics
        assert 'profit_factor' in all_metrics
    
    def test_calculate_profit_factor(self, sample_equity_curve, sample_trade_history):
        """Test profit factor calculation."""
        metrics = PerformanceMetrics(
            equity_curve=sample_equity_curve,
            trade_history=sample_trade_history,
            initial_capital=100000.0
        )
        
        profit_factor = metrics.calculate_profit_factor()
        
        assert isinstance(profit_factor, float)
        # With wins of 150+200+75=425 and losses of 50+100=150
        # Profit factor should be > 1 (profitable)


class TestBacktestEvents:
    """Tests for backtest event types."""
    
    def test_event_types_exist(self):
        """Test that all event types exist."""
        assert EventType.MARKET is not None
        assert EventType.SIGNAL is not None
        assert EventType.ORDER is not None
        assert EventType.FILL is not None
    
    def test_fill_event_creation(self):
        """Test creating a FillEvent."""
        fill = FillEvent(
            symbol='EUR/USD',
            quantity=1000,
            direction='BUY',
            fill_price=1.0850,
            commission=0.50
        )
        
        assert fill.symbol == 'EUR/USD'
        assert fill.quantity == 1000
        assert fill.direction == 'BUY'
        assert fill.fill_price == 1.0850
        assert fill.commission == 0.50
        assert fill.type == EventType.FILL
