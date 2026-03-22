import pytest
from datetime import datetime
from hopefx.social.marketplace import StrategyMarketplace, StrategyListing

class TestStrategyMarketplace:
    
    def test_list_strategy(self, temp_dir, test_config):
        """Test listing a strategy on marketplace."""
        marketplace = StrategyMarketplace(test_config)
        
        listing = StrategyListing(
            id='test-strat-1',
            name='Test MA Crossover',
            description='Simple moving average crossover',
            price=29.99,
            creator_id='user-123',
            strategy_code='...',
            performance_stats={
                'sharpe': 1.5,
                'max_drawdown': 0.1,
                'win_rate': 0.65
            }
        )
        
        result = marketplace.list_strategy(listing)
        assert result['status'] == 'active'
        assert listing.id in marketplace.get_all_listings()
    
    def test_purchase_strategy(self, temp_dir, test_config):
        """Test purchasing a strategy."""
        marketplace = StrategyMarketplace(test_config)
        
        # Setup listing
        listing = StrategyListing(
            id='strat-2',
            name='Premium Strategy',
            price=99.99,
            creator_id='creator-456'
        )
        marketplace.list_strategy(listing)
        
        # Purchase
        purchase = marketplace.purchase_strategy(
            strategy_id='strat-2',
            buyer_id='buyer-789',
            payment_method='wallet'
        )
        
        assert purchase['status'] == 'completed'
        assert purchase['license_key'] is not None
        
    def test_strategy_validation(self, test_config):
        """Test strategy code validation before listing."""
        marketplace = StrategyMarketplace(test_config)
        
        # Invalid strategy (syntax error)
        invalid_code = "def strategy(invalid syntax"
        
        with pytest.raises(ValueError, match='Invalid strategy code'):
            marketplace.validate_strategy(invalid_code)
        
        # Valid strategy
        valid_code = """
def strategy(data):
    return data['close'] > data['sma_20']
"""
        assert marketplace.validate_strategy(valid_code) is True

    def test_revenue_sharing(self, test_config):
        """Test revenue sharing between platform and creator."""
        marketplace = StrategyMarketplace(test_config)
        
        listing = StrategyListing(
            id='strat-3',
            price=100.0,
            creator_id='creator-1'
        )
        marketplace.list_strategy(listing)
        
        purchase = marketplace.purchase_strategy('strat-3', 'buyer-1')
        
        # Platform takes 20%, creator gets 80%
        assert purchase['platform_fee'] == 20.0
        assert purchase['creator_payout'] == 80.0
