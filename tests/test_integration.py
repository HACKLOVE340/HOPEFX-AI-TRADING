"""
HOPEFX Integration Tests
End-to-end testing of trading system components
"""

import pytest
import asyncio
from datetime import datetime, timedelta

from brain.brain import HOPEFXBrain, SystemState
from brokers import PaperTradingBroker
from risk.manager import RiskManager, RiskConfig
from strategies.manager import StrategyManager
from execution.position_tracker import PositionTracker
from execution.trade_executor import TradeExecutor


@pytest.mark.asyncio
async def test_full_trading_cycle(paper_broker, risk_manager, strategy_manager):
    """Test complete trading cycle from signal to execution"""
    
    # Setup components
    brain = HOPEFXBrain(config={
        'max_decision_history': 10,
        'regime_check_interval': 60
    })
    
    position_tracker = PositionTracker()
    
    executor = TradeExecutor(
        broker=paper_broker,
        risk_manager=risk_manager,
        position_tracker=position_tracker
    )
    
    # Inject components into brain
    brain.inject_components(
        broker=paper_broker,
        risk_manager=risk_manager,
        strategy_manager=strategy_manager,
        price_engine=None  # Would need mock
    )
    
    # Verify initial state
    assert brain.state.system_state == SystemState.INITIALIZING
    
    # Test state transitions
    brain.state.system_state = SystemState.RUNNING
    assert brain.state.system_state == SystemState.RUNNING
    
    # Test emergency stop
    brain.emergency_stop()
    assert brain._emergency_stop == True
    
    # Cleanup
    await brain.shutdown()


@pytest.mark.asyncio
async def test_risk_manager_integration(risk_manager, paper_broker):
    """Test risk manager with actual broker"""
    
    # Get account info
    account = await paper_broker.get_account_info()
    
    # Update risk manager with equity
    risk_manager.update_equity(account['equity'])
    
    # Verify risk assessment
    assessment = risk_manager.assess_risk(account, [])
    
    assert assessment.can_trade == True
    assert assessment.level.value in ['low', 'medium', 'high', 'critical']
    
    # Test position sizing
    sizing = risk_manager.calculate_position_size(
        symbol="EURUSD",
        signal_strength=0.7,
        entry_price=1.0850,
        stop_loss_price=1.0800,
        take_profit_price=1.0950,
        account_equity=account['equity'],
        volatility=0.1
    )
    
    assert sizing.approved == True
    assert sizing.recommended_size > 0
    assert sizing.risk_pct <= risk_manager.config.max_position_size_pct


@pytest.mark.asyncio
async def test_trade_execution_flow(paper_broker, risk_manager):
    """Test complete trade execution flow"""
    
    # Setup price feed mock
    class MockPriceFeed:
        def get_last_price(self, symbol):
            from data.real_time_price_engine import Tick
            return Tick(
                symbol=symbol,
                timestamp=datetime.now().timestamp(),
                bid=1.0850,
                ask=1.0852,
                mid=1.0851,
                volume=1000
            )
    
    paper_broker.set_price_feed(MockPriceFeed())
    
    # Place order
    order = await paper_broker.place_market_order(
        symbol="EURUSD",
        side="buy",
        quantity=10000
    )
    
    assert order.status.value in ['filled', 'partial']
    assert order.filled_quantity > 0
    assert order.average_fill_price > 0
    
    # Verify position created
    positions = await paper_broker.get_positions()
    assert len(positions) > 0
    
    # Close position
    position_id = positions[0].id
    success = await paper_broker.close_position(position_id)
    assert success == True
    
    # Verify closed
    positions = await paper_broker.get_positions()
    assert len(positions) == 0


@pytest.mark.asyncio
async def test_circuit_breaker_behavior():
    """Test circuit breaker under failure conditions"""
    
    from utils import CircuitBreaker
    
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
    
    # Initial state
    assert cb.is_open == False
    assert cb.can_execute() == True
    
    # Record failures
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open == False  # Not yet
    
    cb.record_failure()
    assert cb.is_open == True  # Now open
    assert cb.can_execute() == False
    
    # Wait for recovery
    await asyncio.sleep(1.1)
    assert cb.can_execute() == True  # Half-open
    
    # Success should close it
    cb.record_success()
    assert cb.is_open == False
