"""
Comprehensive strategy tests for all trading strategies.
This file aims to increase test coverage to 80%+.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from strategies.base import StrategyConfig


def create_market_data(periods=100, base_price=1.1, trend=0.001, volatility=0.002):
    """Helper to create realistic market data."""
    dates = pd.date_range(start='2023-01-01', periods=periods, freq='h')
    prices = base_price + np.cumsum(np.random.normal(trend, volatility, periods))
    
    return pd.DataFrame({
        'timestamp': dates,
        'open': prices * (1 + np.random.normal(0, 0.0005, periods)),
        'high': prices * (1 + np.abs(np.random.normal(0, 0.001, periods))),
        'low': prices * (1 - np.abs(np.random.normal(0, 0.001, periods))),
        'close': prices,
        'volume': np.random.randint(1000, 10000, periods)
    })


# ==================== SMC/ICT STRATEGY TESTS ====================

@pytest.mark.unit
class TestSMCICTStrategyComprehensive:
    """Comprehensive tests for the SMC/ICT Strategy."""

    @pytest.fixture
    def smc_config(self):
        """Create SMC strategy config."""
        return StrategyConfig(
            name="SMC_Test",
            symbol="EUR_USD",
            timeframe="1H",
            parameters={
                'ob_lookback': 20,
                'fvg_min_gap': 0.001,
                'liquidity_threshold': 0.002
            }
        )

    @pytest.fixture
    def smc_strategy(self, smc_config):
        """Create an SMC/ICT strategy instance."""
        from strategies.smc_ict import SMCICTStrategy
        return SMCICTStrategy(config=smc_config)

    @pytest.fixture
    def smc_market_data(self):
        """Generate market data for SMC tests."""
        return create_market_data(periods=100, base_price=1.1)

    def test_smc_initialization(self, smc_strategy, smc_config):
        """Test SMC/ICT initialization."""
        assert smc_strategy.config.name == "SMC_Test"
        assert smc_strategy.config.symbol == "EUR_USD"
        assert smc_strategy.ob_lookback == 20

    def test_smc_analyze(self, smc_strategy, smc_market_data):
        """Test SMC analyze method."""
        # Convert DataFrame to dict format expected by analyze
        data = {
            'open': smc_market_data['open'].tolist(),
            'high': smc_market_data['high'].tolist(),
            'low': smc_market_data['low'].tolist(),
            'close': smc_market_data['close'].tolist(),
            'volume': smc_market_data['volume'].tolist()
        }
        
        analysis = smc_strategy.analyze(data)
        assert analysis is not None
        assert isinstance(analysis, dict)


# ==================== ITS 8 OS STRATEGY TESTS ====================

@pytest.mark.unit
class TestITS8OSStrategyComprehensive:
    """Comprehensive tests for the ITS 8 OS Strategy."""

    @pytest.fixture
    def its_config(self):
        """Create ITS strategy config."""
        return StrategyConfig(
            name="ITS_Test",
            symbol="EUR_USD",
            timeframe="1H",
            parameters={}
        )

    @pytest.fixture
    def its_strategy(self, its_config):
        """Create an ITS 8 OS strategy instance."""
        from strategies.its_8_os import ITS8OSStrategy
        return ITS8OSStrategy(config=its_config)

    @pytest.fixture
    def its_market_data(self):
        """Generate market data for ITS tests."""
        return create_market_data(periods=100, base_price=1.1)

    def test_its_initialization(self, its_strategy, its_config):
        """Test ITS 8 OS initialization."""
        assert its_strategy.config.name == "ITS_Test"
        assert its_strategy.config.symbol == "EUR_USD"

    def test_its_analyze(self, its_strategy, its_market_data):
        """Test ITS analyze method."""
        data = {
            'open': its_market_data['open'].tolist(),
            'high': its_market_data['high'].tolist(),
            'low': its_market_data['low'].tolist(),
            'close': its_market_data['close'].tolist(),
            'volume': its_market_data['volume'].tolist()
        }
        
        analysis = its_strategy.analyze(data)
        assert analysis is not None
        assert isinstance(analysis, dict)


# ==================== STRATEGY BRAIN TESTS ====================

@pytest.mark.unit
class TestStrategyBrainComprehensive:
    """Comprehensive tests for the Strategy Brain."""

    @pytest.fixture
    def brain_config(self):
        """Create Strategy Brain config (dict, not StrategyConfig)."""
        return {
            'min_strategies_required': 2,
            'consensus_threshold': 0.6,
            'performance_weight': 0.4
        }

    @pytest.fixture
    def brain_strategy(self, brain_config):
        """Create a Strategy Brain instance."""
        from strategies.strategy_brain import StrategyBrain
        return StrategyBrain(config=brain_config)

    @pytest.fixture
    def brain_market_data(self):
        """Generate market data for Brain tests."""
        return create_market_data(periods=100, base_price=1.1)

    def test_brain_initialization(self, brain_strategy, brain_config):
        """Test Strategy Brain initialization."""
        assert brain_strategy.min_strategies_required == 2
        assert brain_strategy.consensus_threshold == 0.6


# ==================== MA CROSSOVER COMPREHENSIVE TESTS ====================

@pytest.mark.unit
class TestMACrossoverComprehensive:
    """Comprehensive tests for Moving Average Crossover."""

    @pytest.fixture
    def ma_config(self):
        """Create MA config."""
        return StrategyConfig(
            name="MA_Test",
            symbol="EUR_USD",
            timeframe="1H",
            parameters={
                'fast_period': 10,
                'slow_period': 20
            }
        )

    @pytest.fixture
    def ma_strategy(self, ma_config):
        """Create a MA Crossover strategy."""
        from strategies.ma_crossover import MovingAverageCrossover
        return MovingAverageCrossover(config=ma_config)

    @pytest.fixture
    def ma_market_data(self):
        """Generate market data for MA tests."""
        return create_market_data(periods=50, base_price=1.1, trend=0.002)

    def test_ma_initialization(self, ma_strategy):
        """Test MA initialization."""
        assert ma_strategy.fast_period == 10
        assert ma_strategy.slow_period == 20

    def test_ma_analyze(self, ma_strategy, ma_market_data):
        """Test MA analyze method."""
        for idx, row in ma_market_data.iterrows():
            data = {'close': row['close']}
            analysis = ma_strategy.analyze(data)
            assert analysis is not None

    def test_ma_generate_signal(self, ma_strategy, ma_market_data):
        """Test MA signal generation."""
        # Process enough data to generate signals
        signal = None
        for idx, row in ma_market_data.iterrows():
            data = {'close': row['close']}
            analysis = ma_strategy.analyze(data)
            signal = ma_strategy.generate_signal(analysis)
        
        # After processing all data, check signal format
        # Signal may be None or a Signal object
        if signal is not None:
            from strategies.base import Signal, SignalType
            assert isinstance(signal, Signal)
            assert isinstance(signal.signal_type, SignalType)


# ==================== STRATEGY MANAGER COMPREHENSIVE TESTS ====================

@pytest.mark.unit
class TestStrategyManagerComprehensive:
    """Comprehensive tests for Strategy Manager."""

    @pytest.fixture
    def manager(self):
        """Create a strategy manager."""
        from strategies.manager import StrategyManager
        return StrategyManager()

    @pytest.fixture
    def sample_strategy(self, test_config, mock_strategy):
        """Create a sample strategy."""
        return mock_strategy("TestStrategy", "EUR_USD")

    def test_manager_register_multiple(self, manager, mock_strategy):
        """Test registering multiple strategies."""
        strat1 = mock_strategy("Strategy1", "EUR_USD")
        strat2 = mock_strategy("Strategy2", "GBP_USD")
        strat3 = mock_strategy("Strategy3", "USD_JPY")
        
        manager.register_strategy(strat1)
        manager.register_strategy(strat2)
        manager.register_strategy(strat3)
        
        assert len(manager.strategies) == 3
        assert "Strategy1" in manager.strategies
        assert "Strategy2" in manager.strategies
        assert "Strategy3" in manager.strategies

    def test_manager_get_performance_summary(self, manager, mock_strategy):
        """Test getting performance summary."""
        strat = mock_strategy("TestStrat", "EUR_USD")
        strat.update_performance(100, 'BUY')
        strat.update_performance(50, 'BUY')
        
        manager.register_strategy(strat)
        
        summary = manager.performance_summary
        assert summary['total_strategies'] == 1

    def test_manager_iterate_strategies(self, manager, mock_strategy):
        """Test iterating over strategies."""
        strat1 = mock_strategy("Strategy1", "EUR_USD")
        strat2 = mock_strategy("Strategy2", "GBP_USD")
        
        manager.register_strategy(strat1)
        manager.register_strategy(strat2)
        
        count = 0
        for name, strategy in manager.strategies.items():
            count += 1
            assert strategy is not None
        
        assert count == 2


# ==================== BASE STRATEGY TESTS ====================

@pytest.mark.unit
class TestBaseStrategyComprehensive:
    """Comprehensive tests for Base Strategy."""

    def test_strategy_config_creation(self):
        """Test creating a StrategyConfig."""
        config = StrategyConfig(
            name="TestStrategy",
            symbol="EUR_USD",
            timeframe="1H",
            enabled=True,
            risk_per_trade=2.0,
            max_positions=5,
            parameters={'fast': 10, 'slow': 20}
        )
        
        assert config.name == "TestStrategy"
        assert config.symbol == "EUR_USD"
        assert config.timeframe == "1H"
        assert config.enabled == True
        assert config.risk_per_trade == 2.0
        assert config.max_positions == 5
        assert config.parameters['fast'] == 10

    def test_signal_type_enum(self):
        """Test SignalType enum values."""
        from strategies.base import SignalType
        
        assert SignalType.BUY.value == "BUY"
        assert SignalType.SELL.value == "SELL"
        assert SignalType.HOLD.value == "HOLD"
        assert SignalType.CLOSE_LONG.value == "CLOSE_LONG"
        assert SignalType.CLOSE_SHORT.value == "CLOSE_SHORT"

    def test_strategy_status_enum(self):
        """Test StrategyStatus enum values."""
        from strategies.base import StrategyStatus
        
        assert StrategyStatus.IDLE.value == "IDLE"
        assert StrategyStatus.RUNNING.value == "RUNNING"
        assert StrategyStatus.PAUSED.value == "PAUSED"
        assert StrategyStatus.STOPPED.value == "STOPPED"
        assert StrategyStatus.ERROR.value == "ERROR"

    def test_signal_creation(self):
        """Test creating a Signal."""
        from strategies.base import Signal, SignalType
        
        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="EUR_USD",
            price=1.1000,
            timestamp=datetime.now(),
            confidence=0.8,
            metadata={'reason': 'test'}
        )
        
        assert signal.signal_type == SignalType.BUY
        assert signal.symbol == "EUR_USD"
        assert signal.price == 1.1000
        assert signal.confidence == 0.8

    def test_signal_invalid_confidence(self):
        """Test Signal with invalid confidence raises error."""
        from strategies.base import Signal, SignalType
        
        with pytest.raises(ValueError):
            Signal(
                signal_type=SignalType.BUY,
                symbol="EUR_USD",
                price=1.1000,
                timestamp=datetime.now(),
                confidence=1.5  # Invalid - should be 0-1
            )
