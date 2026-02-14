"""
Unit tests for Risk Management system.
"""

import pytest
from datetime import datetime

from risk import RiskManager, RiskConfig


@pytest.mark.unit
class TestRiskManager:
    """Test the RiskManager class."""

    def test_risk_manager_initialization(self, risk_manager):
        """Test risk manager initialization."""
        assert risk_manager is not None
        assert risk_manager.max_positions == 5
        assert risk_manager.max_drawdown == 0.10

    def test_calculate_position_size_fixed(self, risk_manager):
        """Test fixed position sizing."""
        result = risk_manager.calculate_position_size(
            symbol="EUR_USD",
            price=1.1000,
            method="fixed",
            amount=10000
        )

        assert result.size > 0
        assert result.size <= risk_manager.max_position_size

    def test_calculate_position_size_percent(self, risk_manager):
        """Test percentage-based position sizing."""
        result = risk_manager.calculate_position_size(
            symbol="EUR_USD",
            price=1.1000,
            method="percent",
            percent=0.02  # 2% of account
        )

        assert result.size > 0

    def test_calculate_position_size_risk_based(self, risk_manager):
        """Test risk-based position sizing."""
        result = risk_manager.calculate_position_size(
            symbol="EUR_USD",
            price=1.1000,
            method="risk",
            stop_loss=1.0950,  # 50 pips stop
            risk_percent=0.01  # Risk 1% of account
        )

        assert result.size > 0

    def test_validate_trade_within_limits(self, risk_manager):
        """Test trade validation within limits."""
        is_valid, reason = risk_manager.validate_trade(
            symbol="EUR_USD",
            size=5000,
            side="BUY"
        )

        assert is_valid == True
        assert reason == ""

    def test_validate_trade_exceeds_position_limit(self, risk_manager):
        """Test trade validation when position limit exceeded."""
        # Fill up to max positions
        for i in range(5):
            risk_manager.open_positions.append({
                'symbol': 'EUR_USD',
                'size': 1000,
                'side': 'BUY'
            })

        is_valid, reason = risk_manager.validate_trade(
            symbol="GBP_USD",
            size=1000,
            side="BUY"
        )

        assert is_valid == False
        assert "max" in reason.lower() and "position" in reason.lower()

    def test_validate_trade_exceeds_size_limit(self, risk_manager):
        """Test trade validation when size limit exceeded."""
        is_valid, reason = risk_manager.validate_trade(
            symbol="EUR_USD",
            size=20000,  # Exceeds max_position_size of 10000
            side="BUY"
        )

        assert is_valid == False
        assert "position size" in reason.lower()

    def test_check_daily_loss_limit(self, risk_manager):
        """Test daily loss limit checking."""
        # Simulate losing trades - exceed 10% loss
        risk_manager.daily_pnl = -15000  # 15% loss on 100k balance

        within_limit, violations = risk_manager.check_risk_limits()

        assert within_limit == False
        assert len(violations) > 0
        assert any("daily loss" in str(v).lower() for v in violations)

    def test_check_drawdown_limit(self, risk_manager):
        """Test drawdown limit checking."""
        # Simulate drawdown - more than 10%
        risk_manager.peak_balance = 100000
        risk_manager.current_balance = 85000  # 15% drawdown

        within_limit, violations = risk_manager.check_risk_limits()

        assert within_limit == False
        assert len(violations) > 0
        assert any("drawdown" in str(v).lower() for v in violations)

    def test_calculate_stop_loss(self, risk_manager):
        """Test stop loss calculation."""
        # Using percentage-based stop loss (2%)
        stop_loss = risk_manager.calculate_stop_loss(
            entry_price=1.1000,
            side="BUY",
            percent=0.2  # 0.2% stop loss
        )

        assert stop_loss < 1.1000  # Stop below entry for BUY
        # 0.2% of 1.1000 = 0.0022
        assert abs(stop_loss - 1.1000) == pytest.approx(0.0022, rel=0.01)

    def test_calculate_take_profit(self, risk_manager):
        """Test take profit calculation."""
        # Using percentage-based take profit (0.4%)
        take_profit = risk_manager.calculate_take_profit(
            entry_price=1.1000,
            side="BUY",
            percent=0.4  # 0.4% take profit
        )

        assert take_profit > 1.1000  # Target above entry for BUY
        # 0.4% of 1.1000 = 0.0044
        assert abs(take_profit - 1.1000) == pytest.approx(0.0044, rel=0.01)

    def test_update_daily_pnl(self, risk_manager):
        """Test daily P&L tracking."""
        initial_pnl = risk_manager.daily_pnl

        risk_manager.update_daily_pnl(100)
        assert risk_manager.daily_pnl == initial_pnl + 100

        risk_manager.update_daily_pnl(-50)
        assert risk_manager.daily_pnl == initial_pnl + 50

    def test_reset_daily_stats(self, risk_manager):
        """Test resetting daily statistics."""
        risk_manager.daily_pnl = 500
        risk_manager.daily_trades = 10

        risk_manager.reset_daily_stats()

        assert risk_manager.daily_pnl == 0
        assert risk_manager.daily_trades == 0

    def test_get_risk_metrics(self, risk_manager):
        """Test getting risk metrics."""
        metrics = risk_manager.get_risk_metrics()

        assert 'open_positions' in metrics
        assert 'daily_pnl' in metrics
        assert 'max_drawdown' in metrics
        assert 'max_daily_loss' in metrics
        assert isinstance(metrics, dict)
