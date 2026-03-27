# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for risk management.
"""

import pytest
from decimal import Decimal

from core.domain_models import Account
from risk.manager import RiskManager, RiskConfig
from risk.position_sizing import PositionSizer
from kill_switch import KillSwitch


@pytest.fixture
def test_account():
    return Account(
        broker="PAPER",
        account_id="TEST_001",
        balance=Decimal("100000"),
        equity=Decimal("100000"),
        margin_used=Decimal("0"),
        margin_available=Decimal("100000"),
        open_positions={},
        daily_pnl=Decimal("0"),
        total_pnl=Decimal("0"),
        max_drawdown=Decimal("0"),
    )


def test_position_sizing_atr(test_account):
    """Test ATR-based position sizing."""
    sizer = PositionSizer(method="atr")

    size = sizer.calculate_size(
        account=test_account, entry_price=Decimal("1800"), atr=Decimal("2.0")
    )

    # Should be reasonable size
    assert size > 0
    assert size <= Decimal("100")  # Max position limit


def test_kill_switch_trigger(tmp_path):
    """Test kill switch activation and manual reset."""
    flag_file = tmp_path / "ks.flag"
    ks = KillSwitch(flag_file=flag_file)

    assert not ks.is_active()

    ks.activate("Test trigger")
    assert ks.is_active()

    # Deactivation without a token should raise PermissionError
    with pytest.raises(PermissionError):
        ks.deactivate(token=None)

    # Deactivation with the correct token should succeed
    ks._deactivation_token = "test-secret"
    ks.deactivate(token="test-secret")
    assert not ks.is_active()


def test_risk_manager_signal_validation(tmp_path):
    """Test risk manager kill-switch integration via drawdown circuit breaker."""
    config = RiskConfig(max_drawdown_pct=0.05)  # 5% max drawdown
    manager = RiskManager(
        config=config,
        initial_balance=100_000.0,
        halt_state_file=tmp_path / "halt_state.json",
    )

    # Kill switch should not be active initially
    assert not manager.kill_switch_active

    # Establish peak equity then drop 7% to breach the 5% drawdown limit
    manager.peak_equity = 100_000.0
    manager.daily_starting_equity = 100_000.0
    manager.update_equity(93_000.0)  # 7% drawdown > 5% limit

    assert manager.kill_switch_active
