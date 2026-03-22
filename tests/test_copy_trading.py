import pytest
import asyncio
from hopefx.social.copy_trading import CopyTradingEngine, CopyTrader
from social.copy_trading import RiskLimitExceeded

class TestCopyTradingEngine:
    
    @pytest.mark.asyncio
    async def test_copy_trade_proportional(self, test_config, mock_broker):
        """Test proportional trade copying."""
        engine = CopyTradingEngine(test_config)
        
        # Leader opens position
        leader_trade = {
            'symbol': 'XAUUSD',
            'side': 'buy',
            'quantity': 1.0,
            'price': 2000.0
        }
        
        # Follower with 50% copy ratio and smaller balance
        follower_config = {
            'follower_id': 'follower-1',
            'leader_id': 'leader-1',
            'copy_ratio': 0.5,
            'max_position_size': 0.5
        }
        
        copied_trade = await engine.copy_trade(
            leader_trade=leader_trade,
            follower_config=follower_config,
            follower_balance=50000  # Half of leader
        )
        
        # Should copy 0.25 lots (0.5 ratio * 0.5 balance ratio)
        assert copied_trade['quantity'] == 0.25
        assert copied_trade['symbol'] == 'XAUUSD'
    
    @pytest.mark.asyncio
    async def test_risk_limits_copy_trading(self, test_config):
        """Test that copy trading respects risk limits."""
        engine = CopyTradingEngine(test_config)
        
        # Attempt to copy trade exceeding max position
        large_trade = {
            'symbol': 'XAUUSD',
            'quantity': 10.0,  # Too large
            'side': 'buy'
        }
        
        follower_config = {
            'follower_id': 'follower-1',
            'copy_ratio': 1.0,
            'max_position_size': 0.1  # Max 10% of balance
        }
        
        with pytest.raises(RiskLimitExceeded):
            await engine.copy_trade(
                large_trade, follower_config, balance=100000
            )
    
    @pytest.mark.asyncio
    async def test_leaderboard_ranking(self, test_config):
        """Test leaderboard calculation."""
        engine = CopyTradingEngine(test_config)
        
        # Add sample performance data
        traders = [
            {'id': 'trader-1', 'return': 0.25, 'sharpe': 1.5, 'followers': 10},
            {'id': 'trader-2', 'return': 0.15, 'sharpe': 2.0, 'followers': 5},
            {'id': 'trader-3', 'return': 0.30, 'sharpe': 1.2, 'followers': 20}
        ]
        
        leaderboard = engine.calculate_leaderboard(traders)
        
        # Should rank by composite score (return * sharpe * log(followers))
        assert len(leaderboard) == 3
        assert leaderboard[0]['rank'] == 1
