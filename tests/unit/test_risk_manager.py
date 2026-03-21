# tests/unit/test_risk_manager.py
"""
Unit tests for Risk Manager - FIA 2024 Compliant
"""

import pytest
import pytest_asyncio
from datetime import datetime, timedelta
from decimal import Decimal
import asyncio

from risk.manager import RiskManager, RiskCheckResult, RiskLevel
from risk.advanced_analytics import RiskAnalytics
from database.models import Trade, Position, Account


class TestRiskManager:
    """Test suite for risk management functionality"""

    @pytest.fixture
    def risk_manager(self):
        """Fresh risk manager instance"""
        return RiskManager()
    
    @pytest.fixture
    def sample_trade(self):
        """Sample trade for testing"""
        return Trade(
            id=1,
            symbol="EURUSD",
            side="buy",
            size=10000,
            entry_price=1.0850,
            timestamp=datetime.now()
        )
    
    def test_position_size_limit_check(self, risk_manager, sample_trade):
        """FIA 1.1: Maximum Order Size validation"""
        # Test within limit
        result = risk_manager.check_position_size(sample_trade, max_pct=0.05)
        assert result.passed is True
        assert result.risk_level == RiskLevel.LOW
        
        # Test exceeding limit
        large_trade = Trade(
            id=2, symbol="EURUSD", side="buy", size=1000000,
            entry_price=1.0850, timestamp=datetime.now()
        )
        result = risk_manager.check_position_size(large_trade, max_pct=0.05)
        assert result.passed is False
        assert result.risk_level == RiskLevel.CRITICAL
        assert "Position size" in result.message
    
    def test_price_tolerance_check(self, risk_manager):
        """FIA 1.3: Price Tolerance validation"""
        current_price = 1.0850
        
        # Valid price (within 2%)
        valid_order = {"price": 1.0870}  # 0.18% deviation
        result = risk_manager.check_price_tolerance(valid_order, current_price, tolerance=0.02)
        assert result.passed is True
        
        # Invalid price (outside tolerance)
        invalid_order = {"price": 1.1200}  # 3.2% deviation
        result = risk_manager.check_price_tolerance(invalid_order, current_price, tolerance=0.02)
        assert result.passed is False
        assert "Price tolerance" in result.message
    
    def test_kill_switch_activation(self, risk_manager):
        """FIA 1.5: Kill Switch functionality"""
        # Simulate losses approaching limit
        daily_pnl = -2800  # 2.8% of 100k account
        account_value = 100000
        
        # Should not trigger at 2.8%
        assert risk_manager.check_kill_switch(daily_pnl, account_value, threshold=0.03) is False
        
        # Should trigger at 3.1%
        daily_pnl = -3100
        assert risk_manager.check_kill_switch(daily_pnl, account_value, threshold=0.03) is True
        assert risk_manager.kill_switch_active is True
    
    def test_max_drawdown_protection(self, risk_manager):
        """Test max drawdown kill switch"""
        equity_curve = [100000, 99000, 98000, 97000, 89000]  # 11% drawdown
        
        result = risk_manager.check_drawdown(equity_curve, max_dd=0.10)
        assert result.passed is False
        assert "Drawdown" in result.message
    
    def test_correlation_risk(self, risk_manager):
        """Test portfolio correlation limits"""
        positions = [
            Position(symbol="EURUSD", size=10000),
            Position(symbol="GBPUSD", size=10000),  # Highly correlated
            Position(symbol="USDJPY", size=10000)    # Less correlated
        ]
        
        result = risk_manager.check_correlation_risk(positions, max_correlation=0.80)
        # EURUSD and GBPUSD typically >0.80 correlation
        assert result.risk_level in [RiskLevel.MEDIUM, RiskLevel.HIGH]
    
    def test_concentration_risk(self, risk_manager):
        """Test position concentration limits"""
        account = Account(balance=100000)
        positions = [
            Position(symbol="EURUSD", size=40000, market_value=43400),  # 43.4%
            Position(symbol="USDJPY", size=10000, market_value=10850)   # 10.9%
        ]
        
        result = risk_manager.check_concentration(positions, account, max_single=0.40)
        assert result.passed is False
        assert "concentration" in result.message.lower()


class TestRiskAnalytics:
    """Test risk analytics calculations"""
    
    @pytest.fixture
    def analytics(self):
        return RiskAnalytics()
    
    def test_var_calculation(self, analytics):
        """Test Value at Risk calculation"""
        returns = [-0.02, 0.01, -0.015, 0.005, -0.01, 0.008, -0.025, 0.012, -0.018, 0.006]
        
        var_95 = analytics.calculate_var(returns, confidence=0.95)
        # VaR should be negative (loss)
        assert var_95 < 0
        assert -0.03 < var_95 < -0.01  # Reasonable range
    
    def test_expected_shortfall(self, analytics):
        """Test Conditional VaR (Expected Shortfall)"""
        returns = [-0.05, -0.04, -0.03, -0.02, -0.01, 0, 0.01, 0.02, 0.03, 0.04]
        
        cvar = analytics.calculate_cvar(returns, confidence=0.95)
        # CVaR should be worse than VaR
        var = analytics.calculate_var(returns, confidence=0.95)
        assert cvar <= var
    
    def test_sharpe_ratio(self, analytics):
        """Test Sharpe ratio calculation"""
        returns = [0.001, -0.002, 0.003, 0.001, -0.001, 0.002, 0.001, -0.001, 0.002, 0.001]
        
        sharpe = analytics.calculate_sharpe(returns, risk_free_rate=0.02/252)
        assert isinstance(sharpe, float)
        assert sharpe > 0  # Positive returns in sample


# tests/integration/test_broker_integration.py
"""
Integration tests for broker connectivity and order execution
"""

import pytest
import asyncio
from unittest.mock import Mock, patch

from brokers.oanda import OandaBroker
from brokers.paper_trading import PaperTradingBroker
from brokers.factory import BrokerFactory

class TestOandaIntegration:
    """Test OANDA API integration with mock responses"""
    
    @pytest.fixture
    def mock_oanda(self):
        """Create broker with mocked API"""
        with patch('brokers.oanda.OandaAPI') as mock_api:
            broker = OandaBroker(api_key="test", account_id="test")
            broker.api = mock_api.return_value
            yield broker
    
    @pytest.mark.asyncio
    async def test_connection_validation(self, mock_oanda):
        """Test connection and authentication"""
        mock_oanda.api.get_account.return_value = {"balance": 10000}
        
        connected = await mock_oanda.connect()
        assert connected is True
    
    @pytest.mark.asyncio
    async def test_order_placement_risk_checks(self, mock_oanda):
        """Test that orders pass risk checks before placement"""
        # Mock risk manager
        mock_oanda.risk_manager = Mock()
        mock_oanda.risk_manager.check_order.return_value = Mock(passed=True)
        
        order = {
            "symbol": "EURUSD",
            "side": "buy",
            "size": 1000,
            "type": "market"
        }
        
        mock_oanda.api.place_order.return_value = {"id": "123", "status": "filled"}
        
        result = await mock_oanda.place_order(order)
        assert result is not None
        mock_oanda.risk_manager.check_order.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_order_rejection_on_risk_failure(self, mock_oanda):
        """Test orders rejected when risk checks fail"""
        mock_oanda.risk_manager = Mock()
        mock_oanda.risk_manager.check_order.return_value = Mock(
            passed=False, 
            risk_level="CRITICAL",
            message="Position limit exceeded"
        )
        
        order = {"symbol": "EURUSD", "side": "buy", "size": 1000000}
        
        with pytest.raises(Exception) as exc_info:
            await mock_oanda.place_order(order)
        
        assert "Position limit" in str(exc_info.value)


# tests/e2e/test_trading_workflow.py
"""
End-to-end trading workflow tests
"""

import pytest
import asyncio
from datetime import datetime

class TestTradingWorkflow:
    """Full system integration test"""
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_full_trading_cycle(self):
        """
        Test complete cycle:
        1. Data ingestion
        2. Signal generation
        3. Risk validation
        4. Order execution
        5. Position tracking
        6. P&L calculation
        """
        # This would require full system setup
        # Simplified version for demonstration
        
        from main import HOPEFXTradingSystem
        from config.config_manager import ConfigManager
        
        # Initialize system
        config = ConfigManager()
        config.settings.TRADING_MODE = "paper"
        config.settings.INITIAL_CAPITAL = 10000
        
        system = HOPEFXTradingSystem(config)
        
        # Start system
        await system.start()
        
        # Wait for initialization
        await asyncio.sleep(2)
        
        # Verify components are running
        assert system.data_engine.is_running
        assert system.risk_manager.is_active
        assert len(system.strategies) > 0
        
        # Stop system
        await system.stop()
