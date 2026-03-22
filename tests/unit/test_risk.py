"""
Unit tests for risk management.
"""

import pytest
from decimal import Decimal

from src.domain.enums import TradeDirection
from src.domain.models import Account, Signal
from src.risk.manager import RiskManager
from src.risk.position_sizing import PositionSizer
from src.risk.kill_switch import KillSwitch


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
        max_drawdown=Decimal("0")
    )


def test_position_sizing_atr(test_account):
    """Test ATR-based position sizing."""
    sizer = PositionSizer(method="atr")
    
    size = sizer.calculate_size(
        account=test_account,
        entry_price=Decimal("1800"),
        atr=Decimal("2.0")
    )
    
    # Should be reasonable size
    assert size > 0
    assert size <= Decimal("100")  # Max position limit


def test_kill_switch_trigger():
    """Test kill switch activation."""
    ks = KillSwitch()
    
    assert not ks.is_active
    
    ks.trigger("Test trigger")
    assert ks.is_active
    
    # Should not allow reset during cooldown
    assert not ks.reset(manual=False)
    
    # Manual reset should work
    assert ks.reset(manual=True)
    assert not ks.is_active


@pytest.mark.asyncio
async def test_risk_manager_signal_validation(test_account):
    """Test risk manager signal validation."""
    manager = RiskManager(account=test_account)
    await manager.initialize()
    
    signal = Signal(
        strategy_id="test",
        symbol="XAUUSD",
        direction=TradeDirection.LONG,
        strength=0.8,
        confidence=0.9
    )
    
    allowed, reason = await manager.check_signal(signal)
    assert allowed is True
    
    # Trigger kill switch
    manager.kill_switch.trigger("Test")
    
    allowed, reason = await manager.check_signal(signal)
    assert allowed is False
    assert "kill switch" in reason.lower()
