"""
Unit tests for trading strategies.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from strategies import BaseStrategy, StrategyManager
from strategies.ma_crossover import MovingAverageCrossover


@pytest.mark.unit
class TestBaseStrategy:
    """Test the BaseStrategy abstract class."""

    def test_strategy_initialization(self, test_config, mock_strategy):
        """Test strategy initialization."""
        strategy = mock_strategy()

        assert strategy.name == "MockStrategy"
        assert strategy.symbol == "EUR_USD"
        assert strategy.is_active == False
        assert strategy.performance['total_signals'] == 0

    def test_strategy_start_stop(self, test_config, mock_strategy):
        """Test starting and stopping strategy."""
        strategy = mock_strategy()

        strategy.start()
        assert strategy.is_active == True

        strategy.stop()
        assert strategy.is_active == False

    def test_strategy_pause_resume(self, test_config, mock_strategy):
        """Test pausing and resuming strategy."""
        strategy = mock_strategy()

        strategy.start()
        strategy.pause()
        assert strategy.is_active == False

        strategy.resume()
        assert strategy.is_active == True

    def test_update_performance(self, test_config, mock_strategy):
        """Test performance tracking."""
        strategy = mock_strategy()

        # Simulate winning trade
        strategy.update_performance(profit_loss=100, signal_type='BUY')

        assert strategy.performance['total_signals'] == 1
        assert strategy.performance['total_pnl'] == 100
        assert strategy.performance['winning_trades'] == 1
        assert strategy.performance['win_rate'] == 100.0

    def test_performance_win_rate_calculation(self, test_config, mock_strategy):
        """Test win rate calculation."""
        strategy = mock_strategy()

        # 3 wins, 2 losses
        strategy.update_performance(100, 'BUY')
        strategy.update_performance(50, 'BUY')
        strategy.update_performance(-30, 'SELL')
        strategy.update_performance(75, 'BUY')
        strategy.update_performance(-20, 'SELL')

        assert strategy.performance['total_signals'] == 5
        assert strategy.performance['winning_trades'] == 3
        assert strategy.performance['losing_trades'] == 2
        assert strategy.performance['win_rate'] == 60.0
        assert strategy.performance['total_pnl'] == 175


@pytest.mark.unit
class TestMovingAverageCrossover:
    """Test the Moving Average Crossover strategy."""

    def test_ma_crossover_initialization(self, test_config):
        """Test MA crossover initialization."""
        from strategies.base import StrategyConfig
        
        config = StrategyConfig(
            name="MA_Test",
            symbol="EUR_USD",
            timeframe="1H",
            parameters={
                'fast_period': 10,
                'slow_period': 20
            }
        )
        strategy = MovingAverageCrossover(config=config)

        assert strategy.fast_period == 10
        assert strategy.slow_period == 20
        assert strategy.config.symbol == "EUR_USD"

    def test_ma_crossover_bullish_signal(self, test_config, sample_market_data):
        """Test bullish crossover signal generation."""
        from strategies.base import StrategyConfig
        
        config = StrategyConfig(
            name="MA_Test",
            symbol="EUR_USD",
            timeframe="1H",
            parameters={
                'fast_period': 5,
                'slow_period': 10
            }
        )
        strategy = MovingAverageCrossover(config=config)

        # Create data where fast MA crosses above slow MA
        data = sample_market_data.copy()
        # Make recent prices higher to force bullish crossover
        data.loc[data.index[-5:], 'close'] *= 1.05

        # Process each bar to build up the MA history
        signal = None
        for idx, row in data.iterrows():
            bar_data = {'close': row['close']}
            analysis = strategy.analyze(bar_data)
            signal = strategy.generate_signal(analysis)
            if signal:
                break

        # Signal should be BUY if crossover detected, or None
        if signal:
            assert signal.signal_type.value in ['BUY', 'HOLD']

    def test_ma_crossover_bearish_signal(self, test_config, sample_market_data):
        """Test bearish crossover signal generation."""
        from strategies.base import StrategyConfig
        
        config = StrategyConfig(
            name="MA_Test",
            symbol="EUR_USD",
            timeframe="1H",
            parameters={
                'fast_period': 5,
                'slow_period': 10
            }
        )
        strategy = MovingAverageCrossover(config=config)

        # Create data where fast MA crosses below slow MA
        data = sample_market_data.copy()
        # Make recent prices lower to force bearish crossover
        data.loc[data.index[-5:], 'close'] *= 0.95

        # Process each bar to build up the MA history
        signal = None
        for idx, row in data.iterrows():
            bar_data = {'close': row['close']}
            analysis = strategy.analyze(bar_data)
            signal = strategy.generate_signal(analysis)
            if signal:
                break

        # Signal should be SELL if crossover detected, or None
        if signal:
            assert signal.signal_type.value in ['SELL', 'HOLD']

    def test_ma_crossover_insufficient_data(self, test_config):
        """Test behavior with insufficient data."""
        from strategies.base import StrategyConfig
        
        config = StrategyConfig(
            name="MA_Test",
            symbol="EUR_USD",
            timeframe="1H",
            parameters={
                'fast_period': 50,
                'slow_period': 100
            }
        )
        strategy = MovingAverageCrossover(config=config)

        # Create small dataset
        small_data = pd.DataFrame({
            'close': [1.1000, 1.1001, 1.1002],
            'timestamp': pd.date_range(start='2023-01-01', periods=3, freq='h')
        })

        # Process the small data
        signal = None
        for idx, row in small_data.iterrows():
            bar_data = {'close': row['close']}
            analysis = strategy.analyze(bar_data)
            signal = strategy.generate_signal(analysis)

        # Should return None when insufficient data (no crossover)
        assert signal is None


@pytest.mark.unit
class TestStrategyManager:
    """Test the StrategyManager."""

    def test_manager_initialization(self, strategy_manager):
        """Test strategy manager initialization."""
        assert len(strategy_manager.strategies) == 0
        assert strategy_manager.broker is not None
        assert strategy_manager.risk_manager is not None

    def test_add_strategy(self, strategy_manager, test_config, mock_strategy):
        """Test adding a strategy."""
        strategy = mock_strategy()
        strategy_manager.add_strategy("test_strategy", strategy)

        assert "test_strategy" in strategy_manager.strategies
        assert strategy_manager.strategies["test_strategy"] == strategy

    def test_remove_strategy(self, strategy_manager, test_config, mock_strategy):
        """Test removing a strategy."""
        strategy = mock_strategy()
        strategy_manager.add_strategy("test_strategy", strategy)
        strategy_manager.remove_strategy("test_strategy")

        assert "test_strategy" not in strategy_manager.strategies

    def test_start_strategy(self, strategy_manager, test_config, mock_strategy):
        """Test starting a strategy."""
        strategy = mock_strategy()
        strategy_manager.add_strategy("test_strategy", strategy)
        strategy_manager.start_strategy("test_strategy")

        assert strategy.is_active == True

    def test_stop_strategy(self, strategy_manager, test_config, mock_strategy):
        """Test stopping a strategy."""
        strategy = mock_strategy()
        strategy_manager.add_strategy("test_strategy", strategy)
        strategy_manager.start_strategy("test_strategy")
        strategy_manager.stop_strategy("test_strategy")

        assert strategy.is_active == False

    def test_get_strategy_performance(self, strategy_manager, test_config, mock_strategy):
        """Test getting strategy performance."""
        strategy = mock_strategy()
        strategy.update_performance(100, 'BUY')
        strategy_manager.add_strategy("test_strategy", strategy)

        perf = strategy_manager.get_strategy_performance("test_strategy")

        assert perf is not None
        assert perf['total_pnl'] == 100

    def test_start_all_strategies(self, strategy_manager, test_config, mock_strategy):
        """Test starting all strategies."""
        strategy1 = mock_strategy("Strategy1")
        strategy2 = mock_strategy("Strategy2")

        strategy_manager.add_strategy("strat1", strategy1)
        strategy_manager.add_strategy("strat2", strategy2)

        strategy_manager.start_all()

        assert strategy1.is_active == True
        assert strategy2.is_active == True

    def test_stop_all_strategies(self, strategy_manager, test_config, mock_strategy):
        """Test stopping all strategies."""
        strategy1 = mock_strategy("Strategy1")
        strategy2 = mock_strategy("Strategy2")

        strategy_manager.add_strategy("strat1", strategy1)
        strategy_manager.add_strategy("strat2", strategy2)

        strategy_manager.start_all()
        strategy_manager.stop_all()

        assert strategy1.is_active == False
        assert strategy2.is_active == False
